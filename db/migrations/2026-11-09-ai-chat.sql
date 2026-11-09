-- 앱 'AI 채팅'(어르신의 글 말동무 대화)과 보호자에게 가는 요약.
-- 어르신이 지워지면 CASCADE로 대화·요약도 같이 지워진다. 기존 데이터는 바뀌지 않는다.
-- 위급한 말 알림은 기존 alerts 표의 'emergency_keyword' 종류를 쓴다(표 바꿈 없음).

-- 대화 한 덩이. 마지막 말 뒤로 30분 넘게 조용하면 끝난 것으로 보고, 그다음 말은 새 덩이가 된다.
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id      BIGSERIAL PRIMARY KEY,
    elder_id        BIGINT NOT NULL REFERENCES elders(elder_id) ON DELETE CASCADE,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_message_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 보호자 앱에 보이는 요약(한두 문장). 어르신이 공유에 동의하고 보호자가 열 때 처음 만든다. 요약할 수 없으면 NULL.
    summary         TEXT,
    summary_model   TEXT,
    -- 요약을 시도한 시각. summary가 NULL이어도 채워지면 다시 시도하지 않는다.
    summarized_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS chat_sessions_elder_idx ON chat_sessions (elder_id, last_message_at DESC);

-- 주고받은 말. 원문은 보호자에게 보이지 않고(요약만), 30일이 지나면 지운다.
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id  BIGSERIAL PRIMARY KEY,
    session_id  BIGINT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('elder', 'ai')),
    content     TEXT NOT NULL,
    -- 어르신의 말에서 위급한 표현이 잡힌 분류(규칙이 정한다).
    urgent      TEXT CHECK (urgent IN ('medical', 'fall', 'self_harm', 'help')),
    -- 이 말 때문에 보호자에게 알림을 보낸 시각. 같은 어르신께 하루에 한 번만 보낸다.
    alerted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chat_messages_session_idx ON chat_messages (session_id, message_id);
CREATE INDEX IF NOT EXISTS chat_messages_created_idx ON chat_messages (created_at);
