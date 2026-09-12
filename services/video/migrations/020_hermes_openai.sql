-- Paid OpenAI is a separate provider. Never reclassify subscription/Gemini
-- attempts, release their reservations, or alter their immutable snapshots.
ALTER TABLE hermes_tasks
    DROP CONSTRAINT hermes_tasks_provider_check,
    ADD CONSTRAINT hermes_tasks_provider_check CHECK (
        provider IN ('gemini','chatgpt_subscription','openai_api')),
    DROP CONSTRAINT hermes_task_provider_identity,
    ADD CONSTRAINT hermes_task_provider_identity CHECK (
        (provider='gemini' AND model='gemini-3.8-flash' AND connection_generation IS NULL)
        OR (provider='chatgpt_subscription' AND model='gpt-5.4' AND connection_generation IS NOT NULL)
        OR (provider='openai_api' AND model='gpt-5.6-sol' AND connection_generation IS NULL)
    );
