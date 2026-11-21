
import pytest
from queue_helpers import _set, queue_env, status, wait_until

from note_taker import imaging
from note_taker.extractors.fake import FakeExtractor
from note_taker.models import (
    CaptureStatus,
)

# Rotation detection is exercised explicitly; elsewhere it must be inert and fast.
pytestmark = pytest.mark.usefixtures("no_osd")


@pytest.fixture
def env(data_paths, make_image):
    yield from queue_env(data_paths, make_image)


def test_queue_sets_detected_rotation_once_and_keeps_user_value(env, monkeypatch):
    detected = []

    def fake_detect(path):
        detected.append(path.name)
        return 270

    monkeypatch.setattr(imaging, "detect_rotation", fake_detect)
    b = env.store.create(None).id
    auto = env.add(b, "a.png")
    user = env.add(b, "b.png", rotation=90)
    ext = FakeExtractor()
    q = env.queue(ext)
    q.start()
    q.enqueue(b, auto)
    q.enqueue(b, user)
    wait_until(lambda: len(ext.calls) == 2)
    wait_until(lambda: status(env, b, user) == CaptureStatus.ready)
    assert env.cap(b, auto).rotation == 270
    assert env.cap(b, user).rotation == 90
    assert detected == [env.cap(b, auto).image_file]
    assert [r for _, r in ext.calls] == [270, 90]

    # The user decides the detector was wrong and retries upright: no re-detection.
    env.store.modify(b, lambda batch: _set(batch, auto, rotation=0, status=CaptureStatus.pending))
    q.enqueue(b, auto)
    wait_until(lambda: len(ext.calls) == 3)
    wait_until(lambda: status(env, b, auto) == CaptureStatus.ready)
    assert env.cap(b, auto).rotation == 0
    assert ext.calls[-1][1] == 0
    assert len(detected) == 1
