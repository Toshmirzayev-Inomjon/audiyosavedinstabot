CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    username VARCHAR(128),
    full_name VARCHAR(256) NOT NULL DEFAULT '',
    language VARCHAR(8) NOT NULL DEFAULT 'uz',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS media_cache (
    id BIGSERIAL PRIMARY KEY,
    cache_key VARCHAR(96) UNIQUE NOT NULL,
    normalized_url TEXT NOT NULL,
    platform VARCHAR(64) NOT NULL,
    media_type VARCHAR(24) NOT NULL,
    quality VARCHAR(24) NOT NULL DEFAULT '',
    telegram_file_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    artist TEXT NOT NULL DEFAULT '',
    duration INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_media_cache_lookup ON media_cache(cache_key);
CREATE INDEX IF NOT EXISTS idx_media_cache_url_type
ON media_cache(normalized_url, media_type, quality);

CREATE TABLE IF NOT EXISTS downloads (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    chat_id BIGINT NOT NULL,
    status_message_id BIGINT,
    original_url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    platform VARCHAR(64) NOT NULL,
    media_type VARCHAR(24) NOT NULL,
    quality VARCHAR(24) NOT NULL DEFAULT '',
    status VARCHAR(24) NOT NULL DEFAULT 'queued',
    progress_percent INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NOT NULL DEFAULT '',
    telegram_file_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_downloads_user_created ON downloads(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
