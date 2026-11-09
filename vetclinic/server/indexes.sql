
CREATE INDEX IF NOT EXISTS idx_app_status ON appointments (status);

CREATE INDEX IF NOT EXISTS idx_app_phone ON appointments (phone);

CREATE INDEX IF NOT EXISTS idx_app_created_service ON appointments (created_at, service_id);
