# Judge audit

Chạy (trong `src/`): `python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 10` và `... judge_helpful_public.csv --audit 21`.
Positive = **FAIL** (việc của judge là tìm lỗi). Judge = replay verdict lưu trong CSV (MockLLM, không API key).

| Tiêu chí | n | κ | Precision | Recall | Confusion (tp/fp/fn/tn) | Fail rate quan sát → Rogan-Gladen | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | 24 / 4 / 6 / 66 | 0.28 → 0.30 | ✅ PASS (exit 0) | **dùng** (non-blocking, kèm người kiểm ngẫu nhiên) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | 9 / 0 / 21 / 70 | 0.09 → 0.30 | ❌ FAIL (κ, R dưới sàn; exit 1) | **loại** khỏi gate |

## ≥5 case audit thủ công

### tone_ok — 10/10 bất đồng

| # | Case | Judge nói | Người nói | Ai đúng? | Sửa rubric / hành động |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Thêm tiêu chí xưng hô: xưng "LogiX"/"anh/chị", không "em … nha"; thêm ví dụ FAIL few-shot |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn…" | PASS | FAIL | Người | Cùng tiêu chí xưng hô: "bạn" với khách = FAIL dù giọng thân thiện |
| 3 | H-029 "…không cần nhắn thêm." | PASS | FAIL | Người | Rubric: câu ra lệnh / cắt ngang khách = FAIL, kể cả có "Dạ, vui lòng" ở đầu |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Ghi rõ: **không yêu cầu xin lỗi**; ngắn đủ ý = PASS (chống verbosity bias) |
| 5 | H-051 "…đã refund 90.000đ…" | FAIL | PASS | Người | Thêm whitelist từ CS cho phép ("refund", "ship") |
| 6 | H-063 "…và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người | Không phải lỗi giọng điệu mà là hứa ngoài kết quả hệ thống → **tách mode**, chấm bằng code (so reply với ledger, FM-08); bỏ khỏi rubric tone |
| 7 | H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Rubric: emoji cười trong ngữ cảnh khiếu nại = FAIL |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** (nhãn người sai — đọc nhầm ticket) | **Sửa nhãn người** + ghi log sửa nhãn; không sửa rubric |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn…" | FAIL | PASS | Người (lỗi gõ nhẹ) | Rubric: lặp từ do gõ không làm hỏng giọng điệu → PASS; chỉ FAIL khi ảnh hưởng nghĩa |
| 10 | H-094 "Da, LogiX da hoan … xin loi…" | PASS | FAIL | Người | Thêm tiêu chí chính tả: mất dấu tiếng Việt / dịch máy = FAIL |

Pattern: 6/6 FN là judge **quá dễ dãi với giọng "thân thiện"** (xưng hô, emoji, mất dấu); 3/4 FP là judge **quá khắt khe về hình thức** (thiếu xin lỗi, từ tiếng Anh, lặp từ). Bất đồng không luôn là lỗi judge: H-081 là nhãn người sai.

### helpful — 21/21 bất đồng đều là FN (judge PASS, người FAIL)

| # | Case | Judge nói | Người nói | Ai đúng? | Sửa rubric / hành động |
|---|---|---|---|---|---|
| 1 | HL-016 xin lỗi dài + "đã hoàn 55.000đ" (ledger 35.000đ) | PASS | FAIL | Người | Verbosity bias: lời xin lỗi dài che số tiền sai → tiền chấm bằng **code** (FM-08), không bằng judge |
| 2 | HL-043 xin lỗi dài + "đã hoàn 35.000đ" (ledger 20.000đ) | PASS | FAIL | Người | Như trên; đúng kịch bản mở bài "91% helpful nhưng sai tiền" |
| 3 | HL-015 "Dạ, LogiX đã hoàn 55.000đ…" (ledger 40.000đ) | PASS | FAIL | Người | Câu ngắn, lịch sự nhưng sai số → judge không có tiêu chí tiền; chuyển sang code grader |
| 4 | HL-087 "…đã hoàn 60.000đ…" (ledger 90.000đ) | PASS | FAIL | Người | Báo thiếu tiền cũng là lỗi → code grader so reply vs ledger 2 chiều |
| 5 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Không nói kết quả/số tiền → thêm tiêu chí "nêu rõ kết quả + số tiền"; giọng điệu giao cho `tone_ok` |

Đếm 21 FN: 13 xin lỗi dài + sai tiền (HL-016, 028, 035, 041, 043, 053, 058, 070, 072, 074, 090, 096, 098), 5 câu ngắn sai tiền (HL-015, 020, 062, 087, 100), 3 câu mơ hồ "Ok bạn…" (HL-047, 091, 097).
→ **18/21 lỗi judge bỏ sót là sai tiền so với ledger** — loại lỗi lẽ ra phải chấm bằng code.

## Kết luận

- **`tone_ok` dùng được**: κ = 0.757, P = 0.857, R = 0.800 đều qua sàn. Dùng như metric năng lực **non-blocking**; sửa rubric theo 9 ca trên (trên public 200 / CSV public, không trên held-out), sửa nhãn H-081.
- **`helpful` bị loại khỏi gate**: P = 1.0 nhưng R = 0.30 (tp 9, fn 21) và κ = 0.375 < 0.6. Judge gần như không bao giờ nói FAIL (9% so với 30% lỗi thật) → dùng làm gate thì **70% phản hồi lỗi lọt qua**. Precision cao chỉ có nghĩa "khi nó nói FAIL thì đúng", không có nghĩa "nó tìm được lỗi".
  - Rogan-Gladen: 0.09 quan sát → **0.30** sau hiệu chỉnh (sens 0.30, spec 1.0) — cùng con số với nhãn người; báo 9% là đánh giá thấp lỗi thật ~3 lần.
  - Nguyên nhân: rubric "helpful" không có tiêu chí tiền + verbosity bias (thưởng lời xin lỗi dài). Sửa đúng: tách mode — số tiền vs ledger → code grader (FM-08, M3); giọng điệu → `tone_ok`; "nêu rõ kết quả" → judge riêng phải calibrate lại.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 mẫu/tiêu chí, 30 FAIL); cần nhãn người mới cho held-out thật (chấm 1 lần), và family swap / order swap với judge thật khi có API.
