# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi bạn 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `<shape> <claim>@<seed>`, run ID trong report |
| Triệu chứng | Grader nào fail; reply nói gì so với ledger ghi gì |
| Bước sai đầu tiên | Số thứ tự event + kind + trích payload (≤1 dòng) |
| Vì sao là bước *đầu tiên* | Các bước trước đó đúng ra sao (dẫn số event) |
| Failure mode | Mã FM-xx trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng claim@seed trên shape `fixed`: bước đó khác thế nào |
| Regression test | Tên test + grader/assert nào bắt được; đã thấy fail trên variant lỗi và pass trên `fixed` chưa |
| Chưa chắc chắn | Điều trace không chứng minh được |

## Case của mình: `seeded_regression` C-008@11 — reply nói 35.000đ, ledger ghi 20.000đ

`python -m lab9.trace_case --shape seeded_regression --claim C-008 --seed 11` (đối chứng: `--shape fixed`)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-008@11`, trace run ID `R-seeded_regression-C-008-s11`, item `E-008` trong `reports/eval_seeded_regression.json` |
| Triệu chứng | Grader Lab 8 **PASS** (status resolved, ledger 20.000 = nhãn); `reply_matches_ledger` **FAIL**: "reply says [35000] but ledger holds 20000". Khách được báo hoàn 35.000đ, thực nhận 20.000đ |
| Bước sai đầu tiên | #5 `reply` `{"text": "Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."}` |
| Vì sao là bước *đầu tiên* | #2 `investigator` đọc đơn O-808 đúng; #3 `quote` 35.000đ (SHIP-LATE-03) đúng; #4 `refund_history` 0đ đã hoàn → không trừ gì, đúng; host cắt theo trần đơn/approval → ghi 20.000đ (đúng nhãn). Sai đầu tiên là #5: reply lấy số **agent đề xuất** (35k) thay vì số **host đã ghi** (20k) |
| Failure mode | FM-08 misreport (layer model/prompt). Nguyên nhân trong variant: công tắc `pre_deducted` cũng bật "báo số tự tính" — FM-05 kéo theo FM-08 |
| Đối chứng | `fixed C-008@11`: #1–#3 giống hệt, không có `refund_history`; #4 `reply` "đã hoàn **20.000đ**" = ledger |
| Regression test | `tests/test_lab9_fm08.py::test_misreport_fails` (Trial dựng tay: ledger 20k, reply 35k → `ReplyMatchesLedger` FAIL) + metric `reply_matches_ledger` (blocking, min 0.95) trong `config/metric_spec.yaml`. Đã thấy: `seeded_regression` 0.786 (E-007, E-008, E-014 fail), `b_misreport` 0.857 (E-008, E-014) → dưới sàn; `fixed` = `swarm` = 1.0 → pass |
| Chưa chắc chắn | Grader chỉ đọc số có đơn vị tiền (`đ`, `đồng`, `VND`); reply nói tiền bằng chữ ("hai mươi nghìn") hoặc không ghi đơn vị sẽ lọt. Shape `swarm` không có event `reply` nên metric này luôn 1.0 trên baseline — nó chỉ có ý nghĩa với shape có reply |

## Kết quả trajectory assertion trên variants (M3)

Trial "lỗi" = trial có kết quả (status/ledger/reply) khác cùng claim@seed trên `fixed`; "phát hiện" = ít nhất một assertion (`pass_rate`, `refund_amount_correct`, `reply_matches_ledger`, `approval_bypass`, `secret_leak`) cờ trial đó.

| Shape | Trial lỗi | Phát hiện | Tỉ lệ |
|---|---|---|---|
| `seeded_regression` | 25 | 25 | 100% |
| `fixed` + `misreport` | 10 | 10 | 100% (chỉ `reply_matches_ledger` bắt; `pass_rate` = 1.0) |
| `fixed` + `sibling_refund` | 20 | 20 | 100% |
| `fixed` + `pre_deducted` | 15 | 15 | 100% |
| `fixed` + `ignore_denied` | 10 | 10 | 100% |
| `fixed` (báo nhầm) | — | 0/70 | **0%** |

Ngưỡng lab: phát hiện ≥ 80%, báo nhầm ≤ 10% → đạt. Giới hạn: đo trên MockLLM tất định, 14 item × 5 seed, variant do GV gài; chưa đo trên cặp ẩn.

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
