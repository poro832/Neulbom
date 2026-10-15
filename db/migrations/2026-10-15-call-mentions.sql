-- 통화 속 건강·기분 언급 (설계: 통화 속 건강·기분 언급 모으기).
-- 기존 서버(RDS)에 한 번 실행한다. 새 설치는 db/schema.sql에 같은 내용이 있다.
-- 원격 DB에 쓰는 일이므로 실행 전에 내용을 확인하고 사용자가 psql로 직접 돌린다.

CREATE TABLE IF NOT EXISTS call_mentions (
    mention_id BIGSERIAL PRIMARY KEY,
    call_id    BIGINT NOT NULL REFERENCES calls(call_id) ON DELETE CASCADE,
    category   TEXT NOT NULL CHECK (category IN ('body', 'sleep', 'meal', 'mood', 'activity')),
    said       TEXT NOT NULL CHECK (said IN ('bad', 'ok', 'good')),
    quote      TEXT NOT NULL CHECK (char_length(quote) BETWEEN 1 AND 40),
    model_id   TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS call_mentions_call_idx ON call_mentions (call_id);

COMMENT ON TABLE call_mentions IS
    '어르신이 통화에서 직접 한 건강·기분 이야기. quote는 어르신 말 그대로(서버가 기록에 있는지 확인). 진단이 아니며 점수·경보에는 쓰지 않는다.';
