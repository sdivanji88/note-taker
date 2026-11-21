import pytest

from note_taker.slug import slugify


@pytest.mark.parametrize(
    "title,slug",
    [
        ("Permutation City", "permutation-city"),
        ("Measure What Matters: OKRs", "measure-what-matters-okrs"),
        ("Ćirković’s Notes", "cirkovics-notes"),
        ("A Philosophy of Software Design", "a-philosophy-of-software-design"),
        ("!!!", "untitled"),
        ("", "untitled"),
        ("  --Hello,   World--  ", "hello-world"),
        ("日本語", "untitled"),
    ],
)
def test_slugify_cases(title, slug):
    assert slugify(title) == slug
