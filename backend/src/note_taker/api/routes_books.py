from fastapi import APIRouter
from pydantic import BaseModel, Field

from note_taker.api.deps import Svc
from note_taker.models import Book, Kind

router = APIRouter()


class BookIn(BaseModel):
    # The title becomes the slug (and so a file name), hence the non-blank pattern.
    title: str = Field(min_length=1, max_length=300, pattern=r"\S")
    author: str | None = Field(default=None, max_length=300)
    kind: Kind


@router.get("/books")
def list_books(svc: Svc) -> list[Book]:
    svc.push.sync()
    return svc.books.list()


@router.post("/books")
def create_book(body: BookIn, svc: Svc) -> Book:
    # The catalog returns the existing book when the slug is already taken.
    return svc.books.create(body.title.strip(), body.author, body.kind)
