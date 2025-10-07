"""Persistence layer for storing comparison scenarios.

This module abstracts persistence so the web app can keep comparison scenarios
in an external database instead of browser cookies. It defaults to SQLite for
local development, but accepts any SQLAlchemy-compatible URL (e.g.
PostgreSQL/MySQL) which is ideal for deployments on Kubernetes or shared
servers.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable, List, Dict, Any

from sqlalchemy import Column, DateTime, String, Text, create_engine, select
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class ComparisonScenarioModel(Base):
    __tablename__ = "comparison_scenarios"

    id = Column(String(64), primary_key=True)
    user_token = Column(String(64), index=True, nullable=False)
    name = Column(String(255), nullable=False)
    summary_json = Column(Text, nullable=False)
    schedule_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ComparisonStore:
    """Database-backed scenario store."""

    def __init__(self, url: str, *, max_per_user: int = 10) -> None:
        self._engine = create_engine(url, future=True)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False, future=True)
        self._max_per_user = max_per_user

    def list_scenarios(self, user_token: str) -> List[Dict[str, Any]]:
        if not user_token:
            return []
        with self._session_factory() as session:
            rows: Iterable[ComparisonScenarioModel] = session.execute(
                select(ComparisonScenarioModel)
                .where(ComparisonScenarioModel.user_token == user_token)
                .order_by(ComparisonScenarioModel.created_at.asc())
            ).scalars()
            return [self._to_dict(row) for row in rows]

    def add_scenario(self, user_token: str, scenario_id: str, name: str, summary: dict, schedule: list) -> None:
        if not user_token:
            return
        payload = ComparisonScenarioModel(
            id=scenario_id,
            user_token=user_token,
            name=name,
            summary_json=json.dumps(summary),
            schedule_json=json.dumps(schedule),
        )
        with self._session_factory() as session:
            session.add(payload)
            session.commit()
        self._trim_user(user_token)

    def remove_scenario(self, user_token: str, scenario_id: str) -> None:
        if not user_token:
            return
        with self._session_factory() as session:
            row = session.get(ComparisonScenarioModel, scenario_id)
            if row and row.user_token == user_token:
                session.delete(row)
                session.commit()

    def clear_scenarios(self, user_token: str) -> None:
        if not user_token:
            return
        with self._session_factory() as session:
            session.execute(
                ComparisonScenarioModel.__table__.delete().where(
                    ComparisonScenarioModel.user_token == user_token
                )
            )
            session.commit()

    def _trim_user(self, user_token: str) -> None:
        if not self._max_per_user or self._max_per_user < 0:
            return
        with self._session_factory() as session:
            rows = session.execute(
                select(ComparisonScenarioModel)
                .where(ComparisonScenarioModel.user_token == user_token)
                .order_by(ComparisonScenarioModel.created_at.desc())
            ).scalars().all()
            if len(rows) <= self._max_per_user:
                return
            for row in rows[self._max_per_user :]:
                session.delete(row)
            session.commit()

    @staticmethod
    def _to_dict(row: ComparisonScenarioModel) -> Dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "summary": json.loads(row.summary_json),
            "schedule": json.loads(row.schedule_json),
            "created_at": row.created_at.isoformat(),
        }


def create_store_from_env(url: str | None) -> ComparisonStore:
    return ComparisonStore(url or "sqlite:///comparison_data.sqlite3")
