-- 어르신 탈퇴는 보호자 전원이 승인해야 한다. 요청은 어르신당 하나이고, 승인은 보호자마다 하나다.
-- 어르신이 지워지면 CASCADE로 같이 지워진다. 기존 데이터는 바뀌지 않는다.
CREATE TABLE IF NOT EXISTS elder_withdrawals (
    elder_id     BIGINT PRIMARY KEY REFERENCES elders(elder_id) ON DELETE CASCADE,
    -- 요청마다 새 번호. 보호자의 승인·거절은 본 요청의 번호를 보내고, 다르면(취소 뒤 다시 요청) 닿지 않는다.
    request_id   BIGINT GENERATED ALWAYS AS IDENTITY,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 보호자가 한 명이라도 거절하면 채운다. 어르신 앱에 거절됐다고 보이고, 어르신은 다시 요청할 수 있다.
    rejected_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS elder_withdrawal_approvals (
    elder_id    BIGINT NOT NULL REFERENCES elder_withdrawals(elder_id) ON DELETE CASCADE,
    guardian_id BIGINT NOT NULL REFERENCES guardians(guardian_id) ON DELETE CASCADE,
    approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (elder_id, guardian_id)
);
