"""Add R-AR1 prompt selection and LLM execution metadata columns."""
from sqlalchemy import create_engine, text

from app.core.config import get_settings


def main():
    engine = create_engine(get_settings().DATABASE_URL)
    with engine.begin() as connection:
        novels = {row[1] for row in connection.execute(text("PRAGMA table_info(novels)"))}
        logs = {row[1] for row in connection.execute(text("PRAGMA table_info(llm_logs)"))}
        if "shot_contract_repair_prompt_template_id" not in novels:
            connection.execute(text(
                "ALTER TABLE novels ADD COLUMN shot_contract_repair_prompt_template_id VARCHAR"))
        if "execution_metadata" not in logs:
            connection.execute(text("ALTER TABLE llm_logs ADD COLUMN execution_metadata JSON"))


if __name__ == "__main__":
    main()
