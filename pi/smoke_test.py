"""services.py のロジック層を、ハードウェア・Slack 無しで一通り確認するスクリプト。

Pi 実機が無くても DB とビジネスロジックを検証できるようにする。
CI ではないので pytest 化はせず、`python smoke_test.py` で assert が全部通れば OK。
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ["OKOZUKAI_HARDWARE"] = "dummy"
os.environ.setdefault("CHANNEL_ID", "CTESTCHANNEL")
os.environ.setdefault("SLACK_APPROVERS", "UTESTAPPROVER1,UTESTAPPROVER2")

with tempfile.TemporaryDirectory() as tmp:
    os.environ["OKOZUKAI_DB_PATH"] = os.path.join(tmp, "smoke.db")

    import config  # noqa: E402
    import db  # noqa: E402
    import services  # noqa: E402
    from hardware import HardwareController  # noqa: E402

    db.init_db()

    posted: list[dict] = []

    def fake_post_message(payload: dict) -> dict:
        posted.append(payload)
        return {"ok": True, "ts": f"ts-{len(posted)}"}

    hardware = HardwareController(balance_provider=db.get_balance)
    services.configure(fake_post_message, hardware)

    # 1) ボタン押下 → 申請作成 → Slack 投稿
    services.handle_button_press("A")
    assert len(posted) == 1, "申請メッセージが投稿されていない"
    row = db.get_request(1)
    assert row["status"] == "pending"
    assert row["slack_ts"] == "ts-1"
    print("OK: press A -> pending request posted")

    # 2) 同日重複
    before = len(posted)
    services.handle_button_press("A")
    assert len(posted) == before, "同日重複なのに投稿されてしまった"
    print("OK: same-day duplicate blocked")

    # 3) 承認
    message = services.decide(1, "approve", config.SLACK_APPROVERS[0])
    assert message is not None
    assert db.get_balance() == 20
    print("OK: approve -> balance=20")

    # 4) 二重クリック
    assert services.decide(1, "approve", config.SLACK_APPROVERS[0]) is None
    print("OK: double-click on decided request is a no-op")

    # 5) 却下(タスク B)
    services.handle_button_press("B")
    row_b = db.get_request(2)
    services.decide(row_b["id"], "reject", config.SLACK_APPROVERS[1])
    assert db.get_balance() == 20, "却下で残高が動いてはいけない"
    print("OK: reject leaves balance unchanged")

    # 6) 任意金額追加(マイナスはメモ必須)
    ok, _ = services.add_manual(config.SLACK_APPROVERS[0], "-50", "")
    assert ok is False, "メモ無しのマイナスが通ってしまった"
    ok, _ = services.add_manual(config.SLACK_APPROVERS[0], "330", "メルカリ")
    assert ok is True
    assert db.get_balance() == 350
    print("OK: manual add/correction validation + balance=350")

    # 7) 全額支払い
    settled, _ = services.pay_all(config.SLACK_APPROVERS[0])
    assert settled == 350
    assert db.get_balance() == 0
    settled_again, _ = services.pay_all(config.SLACK_APPROVERS[0])
    assert settled_again == 0, "残高0円のときに二重精算してしまった"
    print("OK: pay_all settles once, second press is a no-op")

    # 8) history
    result = services.history([])
    assert isinstance(result, dict)
    assert result["response_type"] == "ephemeral"
    print("OK: history returns ephemeral summary")

    # 9) monthly summary (force)
    summary = services.run_monthly_summary(force=True)
    assert summary is not None
    print("OK: monthly summary (forced) produced a message")

    # 10) reconciliation / retry ワーカーが例外を出さないこと
    services.reconciliation_sweep()
    services.retry_unposted_requests()
    print("OK: reconciliation/retry workers ran without error")

    # 11) config モーダルの view_submission パース(正常系)
    values_ok = {
        "task_A_label": {"label": {"value": "お風呂そうじ"}},
        "task_A_amount": {"amount": {"value": "25"}},
        "task_A_dup": {"allow_duplicate_same_day": {"selected_options": [{"value": "A"}]}},
    }
    parsed, errors = services.parse_config_submission(values_ok)
    assert errors == {}
    assert parsed["A"] == {"label": "お風呂そうじ", "amount": 25, "allow_duplicate_same_day": True}
    lines = services.update_tasks(parsed)
    assert len(lines) == 1
    assert db.get_task("A")["label"] == "お風呂そうじ"
    assert db.get_task("A")["amount"] == 25
    print("OK: config modal parse (valid) updates task")

    # 12) config モーダルの view_submission パース(異常系)
    values_bad = {
        "task_B_label": {"label": {"value": "   "}},
        "task_B_amount": {"amount": {"value": "abc"}},
        "task_B_dup": {"allow_duplicate_same_day": {"selected_options": []}},
    }
    parsed_bad, errors_bad = services.parse_config_submission(values_bad)
    assert set(errors_bad.keys()) == {"task_B_label", "task_B_amount"}
    print("OK: config modal parse (invalid) reports errors per block_id")

    # 13) 記帳履歴の一括削除(/okozukai debug の削除ボタン)
    services.add_manual(config.SLACK_APPROVERS[0], "100", "リセットテスト用")
    assert db.get_balance() != 0, "削除前提のテストなのに残高が既に0円"
    services.reset_records()
    assert db.get_balance() == 0
    assert db.get_ledger_range("2000-01-01", "2100-01-01") == []
    assert db.get_request(1) is None
    print("OK: reset_records clears ledger/requests and balance returns to 0")

print("\nALL SMOKE TESTS PASSED")
