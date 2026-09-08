-- Pin each new task to one provider and one owner-auth generation. Existing
-- attempts and Gemini billing reservations remain unchanged.
ALTER TABLE hermes_tasks
    ADD COLUMN provider text NOT NULL DEFAULT 'gemini'
        CHECK (provider IN ('gemini','chatgpt_subscription')),
    ADD COLUMN model text NOT NULL DEFAULT 'gemini-3.8-flash',
    ADD COLUMN connection_generation uuid,
    ADD CONSTRAINT hermes_task_provider_identity CHECK (
        (provider='gemini' AND model='gemini-3.8-flash' AND connection_generation IS NULL)
        OR (provider='chatgpt_subscription' AND model='gpt-5.4' AND connection_generation IS NOT NULL)
    );
