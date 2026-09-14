from sqlalchemy import Text
from sqlalchemy.orm import DeclarativeBase


class BaseSQL(DeclarativeBase):
    type_annotation_map = {str: Text()}
