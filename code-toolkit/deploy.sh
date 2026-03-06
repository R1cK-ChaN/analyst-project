#!/bin/bash
# deploy.sh - Quick setup script for Contabo VPS (Ubuntu)
# Run: chmod +x deploy.sh && ./deploy.sh

echo "=== Macro Analyst Agent - Deployment Setup ==="

# 1. System packages
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv sqlite3

# 2. Create project directory
mkdir -p ~/macro-agent
cd ~/macro-agent

# 3. Python virtual environment
python3 -m venv venv
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Set environment variables
echo "
# Add these to your ~/.bashrc or create a .env file:
# export FRED_API_KEY=your_free_key_from_fred
# export ANTHROPIC_API_KEY=your_key (for LLM calls)
# export TELEGRAM_BOT_TOKEN=your_token (for Sales agent)
"

# 6. Initialize database
python main.py --init-db

# 7. Run initial data fetch
python main.py --once

# 8. Set up systemd service for continuous operation
sudo tee /etc/systemd/system/macro-agent.service > /dev/null << 'EOF'
[Unit]
Description=Macro Analyst Agent Data Pipeline
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/macro-agent
ExecStart=/home/$USER/macro-agent/venv/bin/python main.py --schedule
Restart=always
RestartSec=30
Environment=FRED_API_KEY=your_key_here

[Install]
WantedBy=multi-user.target
EOF

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Get free FRED API key: https://fred.stlouisfed.org/docs/api/api_key.html"
echo "  2. Set your keys: export FRED_API_KEY=xxx"
echo "  3. Test: python main.py --once"
echo "  4. Run continuously: python main.py --schedule"
echo "  5. Or enable service: sudo systemctl enable macro-agent && sudo systemctl start macro-agent"
echo ""
echo "Monitor: journalctl -u macro-agent -f"
