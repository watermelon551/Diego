from __future__ import annotations

from ...models import TemplateRecord
from ..store_support import from_json_payload, to_json_payload


class PostgresTemplateRecordsMixin:
    async def add_template(self, template: TemplateRecord) -> None:
        await self.initialize()
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO diego_templates(template_id, template_json)
                VALUES($1, $2::jsonb)
                ON CONFLICT (template_id) DO UPDATE
                SET template_json=EXCLUDED.template_json, updated_at=NOW()
                """,
                template.template_id,
                to_json_payload(template.model_dump(mode="json")),
            )

    async def get_template(self, template_id: str) -> TemplateRecord | None:
        await self.initialize()
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT template_json FROM diego_templates WHERE template_id=$1",
                template_id,
            )
            if row is None:
                return None
            return TemplateRecord.model_validate(
                from_json_payload(row["template_json"])
            )
