USE agentic_arxiv;

SELECT COLUMN_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA='agentic_arxiv'
  AND TABLE_NAME='users'
  AND COLUMN_NAME IN ('llm_model','llm_base_url','llm_api_key');