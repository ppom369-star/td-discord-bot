# TD Discord Bot

บอทอเนกประสงค์สำหรับเซิร์ฟเวอร์ส่วนตัว พัฒนาด้วย Python (`discord.py`) พร้อมระบบ Keep-Alive Web Server รองรับการรันออนไลน์ฟรี 24/7

---

## ฟีเจอร์ทั้งหมด (Slash Commands)

### 1. Daily Morning Briefing (สรุปยามเช้า)
- `/today [city]` - สรุปภาพรวมยามเช้าทันที (คำสั่งย่อของ `/briefing now`)
- `/briefing now [city]` - สั่งให้บอทสรุปภาพรวมทันที (เปรียบเทียบอากาศบ้านและที่ทำงาน + To-do + พาดหัวข่าวล่าสุด)
- `/briefing set_channel <#channel>` - กำหนดห้องที่จะให้บอทส่งข้อความสรุปอัตโนมัติ
- `/briefing set_time <HH:MM>` - ตั้งเวลาส่งสรุปประจำวัน (เช่น `08:00`)
- `/briefing set_home <city>` - ตั้งพิกัดบ้าน (ค่าเริ่มต้น: `Bang Na` / แบริ่ง)
- `/briefing set_work <city>` - ตั้งพิกัดที่ทำงาน (ค่าเริ่มต้น: `Lat Phrao` / ลาดพร้าว)
- `/briefing set_city <city>` - ตั้งค่าเมืองหลัก

### 2. Weather & Air Quality (สภาพอากาศและฝุ่น PM2.5)
- `/weather <city>` - ตรวจสอบสภาพอากาศ อุณหภูมิ ความชื้น และลม (เช่น `Bangkok`, `Lat Phrao`, `Bang Na`)
- `/pm25 [city]` - เช็คค่าฝุ่น PM2.5, PM10 และดัชนีคุณภาพอากาศ US AQI (พร้อมระดับสีความปลอดภัย)

### 3. To-do List & Reminder (งานและเตือนความจำ)
- `/todo add <task>` - เพิ่มงานใหม่
- `/todo list [status]` - ดูรายการงาน (กรอง: ยังไม่เสร็จ / เสร็จแล้ว / ทั้งหมด)
- `/todo done <id>` - ทำเครื่องหมายว่างานเสร็จแล้ว
- `/todo delete <id>` - ลบงานออกจากรายการ
- `/remind <time> <message>` - ตั้งเวลาเตือนล่วงหน้า (เช่น `10m`, `1h`, `2h30m`, `1d`) บอทจะแท็กเตือนเมื่อถึงเวลา

### 4. News & RSS Feed (ติดตามข่าวสาร)
- `/rss add <url> [#channel]` - เพิ่มฟีดข่าว RSS/Atom พร้อมเลือกห้องแจ้งเตือน
- `/rss list` - ดูรายการฟีดที่ติดตามอยู่
- `/rss remove <id>` - ยกเลิกการติดตามฟีด

### 5. Finance & Crypto (คริปโตและค่าเงิน)
- `/crypto <coin>` - เช็คราคาเหรียญคริปโต (เช่น `btc`, `eth`, `sol`)
- `/rate <from> <to> [amount]` - คำนวณอัตราแลกเปลี่ยนเงินตรา (เช่น `USD` `THB` `100`)

### 6. Utility & System (เครื่องมือทั่วไป)
- `/help` - ดูคู่มือคำสั่งทั้งหมดและคำแนะนำการใช้งานแยกตาม 6 ห้องในเซิร์ฟเวอร์
- `/memo add <title> <content>` - จดบันทึกโน้ตหรือแปะลิงก์
- `/memo list` - ดูโน้ตที่บันทึกไว้
- `/memo delete <id>` - ลบโน้ต
- `/choose <options>` - สุ่มเลือกตัวเลือก เช่น `/choose กะเพรา ข้าวมันไก่ ก๋วยเตี๋ยว`
- `/roll [dice]` - ทอยลูกเต๋า เช่น `1d6`, `2d20`, `1d100`
- `/flip` - โยนเหรียญเสี่ยงทาย (หัว / ก้อย)
- `/ping` - ตรวจสอบความหน่วง (Latency) ของบอท
- `/status` - ดูสถานะ Uptime, RAM, CPU และเวอร์ชันระบบ

---

## การรันบนเครื่องคอมพิวเตอร์ (Local Machine)

1. เปิด PowerShell ในโฟลเดอร์นี้
2. รันบอทผ่าน Virtual Environment:
   ```powershell
   .\venv\Scripts\python main.py
   ```
3. บอทจะเชื่อมต่อ Discord และเริ่มเปิด Web Server ที่พอร์ต `8080` (ตรวจสอบได้ที่ `http://127.0.0.1:8080/health`)

---

## การนำขึ้นโฮสต์ฟรี 24/7 (Deployment Options)

### วิธีที่ 1: Discloud (แนะนำที่สุด — ง่ายและเสถียรสำหรับบอทดิสคอร์ด)
Discloud ให้โควตารัน Discord Bot ฟรี 24/7 โดยไม่ต้องทำเว็บเซิร์ฟเวอร์หลอก และไม่ต้องตั้ง Ping

1. เข้าเว็บ [discloud.com](https://discloud.com/) และล็อกอินด้วยบัญชี Discord
2. บีบอัดไฟล์ในโปรเจกต์นี้ทั้งหมดเป็นไฟล์ `.zip` (ไม่ต้องรวมโฟลเดอร์ `venv` และ `__pycache__` แต่สามารถรวมไฟล์ `bot_data.db` ไปด้วยได้หากต้องการให้ข้อมูล To-do และการตั้งค่าเดิมยังอยู่)
3. ในหน้า Dashboard ของ Discloud ให้กด **Add App** แล้วอัปโหลดไฟล์ `.zip`
4. ใส่ Environment Variable:
   - `DISCORD_TOKEN` = ค่า Token ของคุณ
5. บอทจะเริ่มทำงานออนไลน์ 24/7 ทันที

---

### วิธีที่ 2: Render.com + Cron-Job.org / UptimeRobot (วิธีเดิมที่เคยทำ)
ใช้ Web Service ฟรีของ Render ควบคู่กับตัว Ping

1. สร้าง GitHub Repository (Private) แล้ว Push โค้ดขึ้นไป (ระบบมี `.gitignore` ป้องกัน Token หลุดแล้ว)
2. เข้าเว็บ [render.com](https://render.com/) และเลือก **New +** -> **Web Service**
3. เลือกเชื่อมต่อกับ Repository ของคุณ
4. ตั้งค่าดังนี้:
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
   - **Plan:** `Free`
5. ในหัวข้อ **Environment Variables** ให้เพิ่ม:
   - `DISCORD_TOKEN` = Token ของคุณ
   - `PORT` = `8080`
6. เมื่อ Deploy สำเร็จ คุณจะได้ URL ของเว็บ เช่น `https://td-bot-xxxx.onrender.com`
7. เข้าเว็บ [cron-job.org](https://cron-job.org/) หรือ [uptimerobot.com](https://uptimerobot.com/):
   - สร้าง Monitor/Cron Job ใหม่
   - URL: `https://td-bot-xxxx.onrender.com/health`
   - กำหนดให้ยิงทุกๆ **5 ถึง 10 นาที** เพื่อไม่ให้ Render สั่ง Sleep
