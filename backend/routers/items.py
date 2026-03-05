from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Item
from schemas import ItemResponse
from typing import List

router = APIRouter(
    prefix="/api",
    tags=["items"]
)

@router.get("/items", response_model=List[ItemResponse])
def get_items(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    items = db.query(Item).order_by(Item.created_at.desc()).offset(skip).limit(limit).all()
    return items
