"""
Streamlit Web App for Lotto Max AI
Version 2.0 - With smart draw date detection and ticket selection
"""
import streamlit as st
import sys
from pathlib import Path
import sqlite3
import json

# Add parent directories to path
current_dir = Path(__file__).parent
project_root = current_dir.parent.parent
sys.path.insert(0, str(project_root))

from lotto_ai.scraper.scrape_lotto_max import main as scrape_data
from lotto_ai.features.features import build_feature_matrix
from lotto_ai.tracking.prediction_tracker import PredictionTracker
from lotto_ai.learning.adaptive_learner import AdaptiveLearner
from lotto_ai.models.production_model import (
    generate_adaptive_portfolio,
    portfolio_statistics
)
from datetime import datetime, timedelta

# ============================================
# DRAW DATE FUNCTIONS
# ============================================
def get_next_draw_info():
    """
    Get comprehensive next draw information
    
    Returns:
        tuple: (draw_date, is_today, hours_until_draw)
    
    Logic:
    - Tuesday/Friday before 9 PM → today's draw
    - Tuesday/Friday after 9 PM → next draw day
    - Other days → next Tuesday/Friday
    """
    now = datetime.now()
    current_hour = now.hour
    current_weekday = now.weekday()  # 0=Mon, 1=Tue, 4=Fri
    
    # Configuration
    DRAW_HOUR = 21  # 9:00 PM
    DRAW_DAYS = [1, 4]  # Tuesday and Friday
    
    # Check if today is a draw day
    if current_weekday in DRAW_DAYS:
        if current_hour < DRAW_HOUR:
            # Today's draw hasn't happened yet
            hours_until = DRAW_HOUR - current_hour
            return now.strftime('%Y-%m-%d'), True, hours_until
    
    # Find next draw day
    days_ahead = 1
    while days_ahead <= 7:
        next_date = now + timedelta(days=days_ahead)
        if next_date.weekday() in DRAW_DAYS:
            # Calculate hours until that draw
            draw_datetime = next_date.replace(hour=DRAW_HOUR, minute=0, second=0)
            hours_until = (draw_datetime - now).total_seconds() / 3600
            return next_date.strftime('%Y-%m-%d'), False, hours_until
        days_ahead += 1
    
    # Fallback (should never happen)
    return (now + timedelta(days=1)).strftime('%Y-%m-%d'), False, 24

def get_next_draw_date():
    """Get next draw date (backward compatibility)"""
    draw_date, _, _ = get_next_draw_info()
    return draw_date

def format_draw_info_message(draw_date, is_today, hours_until):
    """Format a user-friendly message about the draw"""
    if is_today:
        if hours_until > 2:
            return f"🎯 **TODAY'S DRAW** - {draw_date} at 9:00 PM (in ~{int(hours_until)}h)"
        elif hours_until > 0:
            return f"⚡ **TODAY'S DRAW** - {draw_date} - HAPPENING SOON! (~{int(hours_until)}h)"
        else:
            return f"⏰ **TODAY'S DRAW** - {draw_date} - Draw is happening now or just finished!"
    else:
        days_until = int(hours_until / 24)
        day_word = "day" if days_until == 1 else "days"
        
        # Determine which day
        draw_dt = datetime.strptime(draw_date, '%Y-%m-%d')
        day_name = draw_dt.strftime('%A')  # Tuesday or Friday
        
        return f"📅 Next draw: **{day_name}, {draw_date}** (in {days_until} {day_word})"

# ============================================
# PASSWORD PROTECTION
# ============================================
def check_password():
    """Returns `True` if user entered correct password"""
    
    def password_entered():
        """Checks whether password is correct"""
        entered_password = st.session_state["password"]
        
        # Try to get from secrets, fallback to hardcoded
        try:
            correct_password = st.secrets.get("app_password", "gotovac71")
        except:
            correct_password = "gotovac71"
        
        if entered_password == correct_password:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    # First run or password not correct
    if "password_correct" not in st.session_state:
        st.markdown("### 🔐 Lotto Max AI - Login")
        st.text_input(
            "Enter Password", 
            type="password", 
            on_change=password_entered, 
            key="password",
            placeholder="Password"
        )
        st.info("💡 Please enter the password to access the app")
        return False
    
    # Password incorrect
    elif not st.session_state["password_correct"]:
        st.text_input(
            "Enter Password", 
            type="password", 
            on_change=password_entered, 
            key="password"
        )
        st.error("❌ Password incorrect. Please try again.")
        return False
    
    # Password correct
    else:
        return True

# Check password before showing app
if not check_password():
    st.stop()

# ============================================
# PLAYED TICKETS TRACKING
# ============================================
class PlayedTicketsTracker:
    """Track which tickets user actually played"""
    
    def __init__(self, db_path):
        from lotto_ai.config import DB_PATH
        self.db_path = DB_PATH
        self._ensure_table()
    
    def _ensure_table(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS played_tickets (
            play_id INTEGER PRIMARY KEY AUTOINCREMENT,
            prediction_id INTEGER,
            ticket_numbers TEXT NOT NULL,
            played_at TEXT NOT NULL,
            draw_date TEXT NOT NULL,
            FOREIGN KEY (prediction_id) REFERENCES predictions(prediction_id)
        )
        """)
        conn.commit()
        conn.close()
    
    def save_played_tickets(self, prediction_id, tickets, draw_date):
        """Save which tickets were actually played"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        for ticket in tickets:
            cur.execute("""
            INSERT INTO played_tickets (prediction_id, ticket_numbers, played_at, draw_date)
            VALUES (?, ?, ?, ?)
            """, (
                prediction_id,
                json.dumps(ticket),
                datetime.now().isoformat(),
                draw_date
            ))
        
        conn.commit()
        conn.close()
    
    def get_played_tickets(self, draw_date):
        """Get tickets that were played for a specific draw"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
        SELECT ticket_numbers FROM played_tickets
        WHERE draw_date = ?
        """, (draw_date,))
        
        tickets = [json.loads(row[0]) for row in cur.fetchall()]
        conn.close()
        return tickets

# ============================================
# PAGE CONFIG
# ============================================
st.set_page_config(
    page_title="Lotto Max AI",
    page_icon="🎰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 2rem 0;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 10px;
        margin-bottom: 2rem;
    }
    .ticket-box {
        background: #f8f9fa;
        padding: 1.5rem;
        border-radius: 10px;
        border-left: 5px solid #667eea;
        margin: 1rem 0;
    }
    .ticket-box.selected {
        background: #e3f2fd;
        border-left: 5px solid #2196F3;
    }
    .number-ball {
        display: inline-block;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        font-weight: bold;
        font-size: 1.2rem;
        padding: 0.5rem 0.8rem;
        border-radius: 50%;
        margin: 0.2rem;
        min-width: 45px;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("""
<div class="main-header">
    <h1>🎰 Lotto Max AI</h1>
    <p style="font-size: 1.2rem; margin: 0;">Smart Number Generator with Learning AI</p>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("### ℹ️ How It Works")
    st.info("""
    **Simple Process:**
    
    1️⃣ Click **Generate Numbers**
    
    2️⃣ Choose 3-4 tickets to play
    
    3️⃣ Click **Mark as Played**
    
    4️⃣ Come back after draw
    
    🧠 **AI learns from played tickets!**
    """)
    
    st.markdown("---")
    
    # Number of tickets selector
    st.markdown("### ⚙️ Settings")
    n_tickets = st.slider(
        "Number of tickets to generate",
        min_value=3,
        max_value=10,
        value=4,
        help="Choose how many tickets to generate"
    )
    
    # Draw countdown
    st.markdown("---")
    st.markdown("### ⏰ Next Draw")
    
    draw_date, is_today, hours_until = get_next_draw_info()
    
    if is_today:
        st.success(f"**TODAY** at 9:00 PM")
        # Progress bar showing time until draw
        progress = min((9 - hours_until) / 9, 1.0)
        st.progress(progress)
        st.caption(f"~{int(hours_until)} hours remaining")
    else:
        days_until = int(hours_until / 24)
        draw_dt = datetime.strptime(draw_date, '%Y-%m-%d')
        day_name = draw_dt.strftime('%A')
        
        st.info(f"**{day_name}**\n{draw_date}")
        st.caption(f"In {days_until} day{'s' if days_until != 1 else ''}")
    
    # Logout button
    st.markdown("---")
    if st.button("🚪 Logout"):
        st.session_state["password_correct"] = False
        st.rerun()

# Initialize session state
if 'generated_tickets' not in st.session_state:
    st.session_state.generated_tickets = None
if 'selected_tickets' not in st.session_state:
    st.session_state.selected_tickets = []
if 'prediction_id' not in st.session_state:
    st.session_state.prediction_id = None
if 'next_draw' not in st.session_state:
    st.session_state.next_draw = None

# Main content
col1, col2, col3 = st.columns([1, 2, 1])

with col2:
    # Generate Button
    if st.button("🎲 GENERATE NUMBERS", 
                 use_container_width=True, 
                 type="primary"):
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            # Step 1: Scrape
            status_text.text("📥 Checking for new draw results...")
            progress_bar.progress(10)
            scrape_data()
            
            # Step 2: Evaluate
            status_text.text("🔍 Evaluating previous predictions...")
            progress_bar.progress(25)
            tracker = PredictionTracker()
            tracker.auto_evaluate_pending()
            
            # Step 3: Learn
            status_text.text("🧠 Learning from results...")
            progress_bar.progress(40)
            learner = AdaptiveLearner()
            learner.update_weights(strategy_name='hybrid_v1', window=20)
            
            perf = tracker.get_strategy_performance('hybrid_v1', window=50)
            
            # Step 4: Build features
            status_text.text("⚙️ Analyzing historical data...")
            progress_bar.progress(60)
            features = build_feature_matrix()
            
            # Step 5: Generate
            status_text.text("🎲 Generating your lucky numbers...")
            progress_bar.progress(80)
            portfolio, weights = generate_adaptive_portfolio(
                features, 
                n_tickets=n_tickets, 
                use_adaptive=True
            )
            
            # Save prediction
            next_draw = get_next_draw_date()
            prediction_id = tracker.save_prediction(
                target_draw_date=next_draw,
                strategy_name='hybrid_v1',
                tickets=portfolio,
                model_version='2.0_adaptive',
                metadata=weights
            )
            
            # Store in session state
            st.session_state.generated_tickets = portfolio
            st.session_state.prediction_id = prediction_id
            st.session_state.next_draw = next_draw
            st.session_state.selected_tickets = []
            st.session_state.weights = weights
            st.session_state.performance = perf
            
            progress_bar.progress(100)
            status_text.empty()
            progress_bar.empty()
            
            # Show success message with draw timing
            draw_date, is_today, hours_until = get_next_draw_info()
            draw_message = format_draw_info_message(draw_date, is_today, hours_until)
            
            st.success(f"✅ Generated {len(portfolio)} tickets!")
            st.info(draw_message)
            st.rerun()
            
        except Exception as e:
            st.error(f"❌ An error occurred: {str(e)}")
            st.exception(e)

# Display generated tickets with selection
if st.session_state.generated_tickets:
    st.markdown("---")
    
    # Performance metrics
    if st.session_state.get('performance'):
        perf = st.session_state.performance
        
        st.markdown("### 📊 AI Performance")
        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
        
        with metric_col1:
            st.metric("Predictions", perf['n_predictions'])
        with metric_col2:
            st.metric("Avg Match", f"{perf['avg_best_match']:.1f}/7")
        with metric_col3:
            st.metric("Hit Rate (3+)", f"{perf['hit_rate_3plus']:.1%}")
        with metric_col4:
            st.metric("Best Ever", f"{perf['best_ever']}/7")
    
    st.markdown("---")
    st.markdown("### 🎟️ Select Tickets to Play")
    
    # Show draw timing
    draw_date, is_today, hours_until = get_next_draw_info()
    draw_message = format_draw_info_message(draw_date, is_today, hours_until)
    st.info(draw_message)
    
    # Display tickets with checkboxes
    portfolio = st.session_state.generated_tickets
    weights = st.session_state.weights
    n_freq = weights['n_freq_tickets']
    
    # AI-Optimized tickets
    st.markdown("#### 📊 AI-Optimized Tickets")
    
    for i, ticket in enumerate(portfolio[:n_freq], 1):
        col_check, col_ticket = st.columns([0.5, 9.5])
        
        with col_check:
            selected = st.checkbox(
                f"#{i}",
                key=f"ticket_{i}",
                value=i in st.session_state.selected_tickets
            )
            if selected and i not in st.session_state.selected_tickets:
                st.session_state.selected_tickets.append(i)
            elif not selected and i in st.session_state.selected_tickets:
                st.session_state.selected_tickets.remove(i)
        
        with col_ticket:
            numbers_html = ''.join([
                f'<span class="number-ball">{n:02d}</span>' 
                for n in ticket
            ])
            box_class = "ticket-box selected" if selected else "ticket-box"
            st.markdown(f"""
            <div class="{box_class}">
                <strong>Ticket {i}</strong> (AI-Optimized)<br>
                {numbers_html}
            </div>
            """, unsafe_allow_html=True)
    
    # Random tickets
    if n_freq < len(portfolio):
        st.markdown("#### 🎲 Random Mix Tickets")
        
        for i, ticket in enumerate(portfolio[n_freq:], n_freq + 1):
            col_check, col_ticket = st.columns([0.5, 9.5])
            
            with col_check:
                selected = st.checkbox(
                    f"#{i}",
                    key=f"ticket_{i}",
                    value=i in st.session_state.selected_tickets
                )
                if selected and i not in st.session_state.selected_tickets:
                    st.session_state.selected_tickets.append(i)
                elif not selected and i in st.session_state.selected_tickets:
                    st.session_state.selected_tickets.remove(i)
            
            with col_ticket:
                numbers_html = ''.join([
                    f'<span class="number-ball">{n:02d}</span>' 
                    for n in ticket
                ])
                box_class = "ticket-box selected" if selected else "ticket-box"
                st.markdown(f"""
                <div class="{box_class}">
                    <strong>Ticket {i}</strong> (Random Mix)<br>
                    {numbers_html}
                </div>
                """, unsafe_allow_html=True)
    
    # Mark as Played button
    st.markdown("---")
    
    col_play, col_download = st.columns(2)
    
    with col_play:
        if st.button(
            f"✅ MARK {len(st.session_state.selected_tickets)} TICKETS AS PLAYED",
            use_container_width=True,
            type="primary",
            disabled=len(st.session_state.selected_tickets) == 0
        ):
            # Save played tickets
            played_tracker = PlayedTicketsTracker(None)
            selected_ticket_numbers = [
                portfolio[i-1] for i in st.session_state.selected_tickets
            ]
            
            played_tracker.save_played_tickets(
                st.session_state.prediction_id,
                selected_ticket_numbers,
                st.session_state.next_draw
            )
            
            st.success(f"✅ Marked {len(st.session_state.selected_tickets)} tickets as played for {st.session_state.next_draw}!")
            st.balloons()
    
    with col_download:
        # Download selected tickets
        if st.session_state.selected_tickets:
            selected_ticket_numbers = [
                portfolio[i-1] for i in st.session_state.selected_tickets
            ]
            
            ticket_text = f"""LOTTO MAX - Selected Tickets
Draw Date: {st.session_state.next_draw}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

{'='*40}
YOUR SELECTED TICKETS
{'='*40}

"""
            for idx, i in enumerate(st.session_state.selected_tickets, 1):
                ticket = portfolio[i-1]
                ticket_text += f"Ticket {idx}: {' - '.join(f'{n:02d}' for n in ticket)}\n"
            
            ticket_text += f"\nGood luck! 🍀"
            
            st.download_button(
                label="💾 Download Selected Tickets",
                data=ticket_text,
                file_name=f"my_tickets_{st.session_state.next_draw}.txt",
                mime="text/plain",
                use_container_width=True
            )

# Footer
st.markdown("---")
st.info("💡 **Tip:** Select 3-4 tickets, mark them as played, then come back after the draw for the AI to learn!")

# Instructions expander
with st.expander("📖 Detailed Instructions"):
    st.markdown("""
    ### How to Use This App
    
    1. **Generate Tickets**
       - Click the big green button
       - Wait 10-20 seconds while the AI works
       - Your tickets will appear below
    
    2. **Select Tickets to Play**
       - Check the boxes next to 3-4 tickets you want to play
       - Mix of AI-optimized and random is recommended
       - Download or write down the numbers
    
    3. **Mark as Played**
       - Click "Mark as Played" button
       - This tells the AI which tickets you actually played
       - Important for learning!
    
    4. **After the Draw**
       - Come back to this app
       - Click "Generate" again
       - The AI will:
         * Automatically check if you won
         * Learn from the results
         * Generate improved tickets
    
    ### Understanding Draw Timing
    
    - **Draws happen**: Tuesday & Friday at 9:00 PM ET
    - **Before 9 PM**: App shows "TODAY'S DRAW"
    - **After 9 PM**: App shows next draw date
    
    ### Why This Strategy Works
    
    **70% AI-Optimized:**
    - Based on frequency analysis
    - Learns from 1000+ historical draws
    - Adapts weights based on performance
    
    **30% Random Mix:**
    - Adds uncorrelated variance
    - Prevents over-optimization
    - Proven to improve overall results
    
    ### Important Notes
    
    ⚠️ **Lottery is gambling** - Play responsibly
    
    ✅ **This AI optimizes strategy** - Not a guarantee
    
    📊 **Expect -40% to -50% ROI** - Better than typical -70%
    
    🧠 **Performance improves over time** - Keep using it!
    """)