"""Category model for organizing sources."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.utils.datetime import utcnow_naive
from app.database import Base, UUIDString


class Category(Base):
    """Category for organizing monitoring sources."""

    __tablename__ = "categories"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(7), default="#1890ff")
    icon = Column(String(50), nullable=True)
    parent_id = Column(UUIDString, ForeignKey("categories.id"), nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Relationships
    parent = relationship("Category", remote_side=[id], backref="children")
    sources = relationship("Source", back_populates="category")

    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name='{self.name}')>"
