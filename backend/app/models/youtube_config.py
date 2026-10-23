"""Private YouTube OAuth settings. Never serialize secrets to API responses."""
from sqlalchemy import Boolean, Column, DateTime, String, Text

from app.core.database import Base


class YoutubeConfig(Base):
    __tablename__ = "youtube_configs"

    id = Column(String, primary_key=True, default="default")
    client_id = Column(String, nullable=False, default="")
    client_secret_encrypted = Column(Text, nullable=False, default="")
    token_encrypted = Column(Text, nullable=False, default="")
    oauth_state = Column(String, nullable=False, default="")
    oauth_state_created_at = Column(DateTime, nullable=True)
    redirect_uri = Column(String, nullable=False, default="")
    default_tags = Column(String, nullable=False, default="")
    proxy_enabled = Column(Boolean, nullable=False, default=False)
    proxy_url = Column(String, nullable=False, default="")
