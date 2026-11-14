## 啟動

1. 解壓縮後進入包含 docker-compose.yml 的 Mini-THSR-Reference 資料夾。
2. 啟動 Docker Desktop，並確認舊專案沒有占用 8080 或 8000。
3. 在該資料夾開終端機，執行：

~~~bash
docker compose up --build
~~~

第一次會下載映像、建置服務並匯入三份 CSV。db-init 完成後正常退出（exit code 0）；前端、後端與資料庫繼續運作。預設不需要先建立 .env。若需要更換連接埠，可複製 .env.example 為 .env，再修改 FRONTEND_PORT 或 API_PORT。

- 前端：http://localhost:8080
- API 測試：http://localhost:8000/users 或 http://localhost:8000/stations
- 測試腳本在 Docker 容器內執行時，依分工說明使用 http://host.docker.internal:8000 作為目標位址，或傳入可連線的 API 位址。

## 操作一次完整流程

1. 選一位 Current User。
2. 搜尋日期 2026-12-07、起站 TPE、迄站 TXG。這是附帶資料的一個示範查詢。
3. 選 Book This Train。訂票頁會顯示該區間的可用座位，可按 Refresh Available Seats 更新。
4. 訂 1 張可輸入 window 或 aisle；也可以選 3 張確認連號。按 Confirm Booking 後，成功才前往 Booking Details。
5. 核對訂單編號、車次、日期、起迄站、座位與 Confirmed 狀態。
6. 按 Cancel Booking。明細應變為 Cancelled，原座位號仍可查。回查相同車次和區間，座位應釋出。
7. 在 Booking Overview 可以查全部訂單或輸入指定訂單編號；換使用者可確認不會查到其他使用者的訂單。

## 專案檔案

| 位置 | 內容 |
|---|---|
| data/ | stations.csv、timetable.csv、users.csv；可換成同格式的測試資料。 |
| schema/schema.sql | 資料表、外鍵、約束、索引與有效車票查詢 view。 |
| backend/db_init.py | 首次啟動讀 CSV，建立停靠序、座位及營運期間內的每日班次。 |
| backend/app/api.py、validation.py | API 路由、輸入檢查及錯誤回應。 |
| backend/app/repository.py | 參數化 SQL，包含共用的區間可用座位判斷。 |
| backend/app/service.py | 選位、交易、訂票與取消時的鎖定。 |
| frontend/ | 查車、訂票、訂單列表、明細頁與 Nginx API 代理。 |
| tests/verify_reference.py | 參考系統的回歸測試，使用獨立測試資料庫。 |

## API 與主要規則

| 方法與路徑 | 參數或行為 |
|---|---|
| GET /users | 全部使用者；回傳 user_id、name。 |
| GET /stations | 全部車站，由北向南排序。 |
| GET /schedules | date、from_station_id、to_station_id；可選 departure_time_from、departure_time_to。依起站發車時間排序，同時刻再依車次排序。剩餘 0 席的車次仍回傳。 |
| GET /seats | train_no、date、from_station_id、to_station_id；回傳 available_seat_count、seats。 |
| POST /bookings | JSON：user_id、train_no、date、from_station_id、to_station_id、seat_count，可選 preference。建立成功回 HTTP 201 與完整訂單。 |
| GET /bookings | user_id，選填 booking_id；回傳列表，包含已取消訂單。 |
| POST /bookings/{booking_id}/cancel | JSON：user_id。取消成功回 HTTP 200 與完整訂單。 |

營運日期為 2026-12-01 至 2027-01-31。日期用 YYYY-MM-DD、時刻用 HH:MM，列車是否行駛由 timetable.csv 的 days 決定。train_no 保留前導零。每節車廂 4 排、每排 5 席，座位排序依車廂、排、字母。

單張票可指定靠窗（A、E）或靠走道（C、D），找不到符合偏好的座位就失敗。2～5 張一定分配同車廂、同一排的連續字母；C、D 相鄰。正式請求不需要 adjacent 欄位。訂單成功才寫入所有車票，取消整筆訂單並保留歷史。

| HTTP | error.code |
|---|---|
| 400 | INVALID_JSON |
| 422 | INVALID_PARAMETER |
| 404 | NOT_FOUND |
| 409 | NO_SEAT、NO_PREFERENCE、NO_ADJACENT_SEATS、ALREADY_CANCELLED |

訂位區間採半開區間，例如 [1, 2) 和 [2, 3) 可以使用同一席。SQL 用 sold.from_stop < requested.to_stop 且 requested.from_stop < sold.to_stop 判斷重疊，只計入同車次、同日期的有效訂單。查車的剩餘數和查座清單共用這個判斷。每次訂票或取消，先在交易內鎖住 train_runs 中「同車次、同日期」那一列，再重新讀取空位或訂單狀態，最後一次提交。這個做法讓不同班次仍可並行，也讓同班次的配位規則容易驗證。

## 停止、資料保存與更換測資

前景執行時按 Ctrl+C 停止。也可以執行 docker compose down；一般停止或重新啟動會保留已匯入的資料與訂單。

如果要換 CSV 測另一組案例，先確認使用的是可以清空的**參考系統測試資料庫**，再執行下列指令。第一行會刪除此 Compose 專案的資料庫 volume 與所有訂單。把新的三份 CSV 放入 data/，以相同檔名取代原檔，再執行第二行。

~~~bash
docker compose down -v
docker compose up --build
~~~

## 參考系統回歸測試

tests/verify_reference.py 使用 PostgreSQL、Flask HTTP 服務及一組替換 CSV，驗證匯入、雙向查車、區間配位、偏好、連號、取消、錯誤碼、同時搶票及重啟後的訂單。它會在指定測試 PostgreSQL 內建立和移除一個隨機命名的暫時資料庫，不改動已存在的資料庫。
