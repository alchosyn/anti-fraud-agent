# 启动后端 (新窗口)
Start-Process powershell -ArgumentList "-Command", "cd D:\pycharmproject\anti-fraud-agent; python -m uvicorn backend.main:app --port 8000; pause"

# 等后端就绪
Start-Sleep -Seconds 2

# 启动前端 (新窗口)
Start-Process powershell -ArgumentList "-Command", "cd D:\pycharmproject\anti-fraud-agent\frontend; npm run dev; pause"

# 等前端就绪后自动打开浏览器
Start-Sleep -Seconds 3
Start-Process "http://localhost:5173"
