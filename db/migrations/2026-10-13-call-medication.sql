-- 약 복용 확인 (설계: docs/plans/2026-10-13-medication-check-design.md).
-- 기존 서버(RDS)에 한 번 실행한다. 새 설치는 db/schema.sql에 같은 내용이 있다.
-- 원격 DB에 쓰는 일이므로 실행 전에 내용을 확인하고 사용자가 psql로 직접 돌린다.

CREATE TABLE IF NOT EXISTS call_medication (
    call_id    BIGINT PRIMARY KEY REFERENCES calls(call_id) ON DELETE CASCADE,
    status     TEXT NOT NULL CHECK (status IN ('taken', 'not_taken', 'unknown')),
    model_id   TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE call_medication IS
    '어르신이 약을 먹었다고 말했는지(통화별). LLM이 어르신의 말을 셋으로 나눈 것일 뿐 점수·경보에는 쓰지 않는다.';
