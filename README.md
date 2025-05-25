# Waiting App - Kiosk Queue Management

This is a standalone Flask application for managing the kiosk check-in queue. It provides staff with tools to view and manage member check-ins from the kiosk system.

## Features

- View waiting queue with real-time updates
- Handle member check-ins (mark as handled)
- View member details with DNA and MeridianLink integration
- Transaction history viewing
- AI-powered insights generation
- Background data pre-fetching for performance
- Caching system for improved response times

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up environment variables in `.env` file:
```bash
FLASK_SECRET_KEY=your_secret_key
FLASK_DEBUG=False
DNA_VERIFY_SSL=false
ML_VERIFY_SSL=false
WAITING_PORT=8082

# Database Configuration
DB_SERVER=your_db_server
DB_NAME=your_db_name
DB_USERNAME=your_db_username
DB_PASSWORD=your_db_password
DB_TABLE=your_visitor_table_name
DB_KIOSK_TABLE=your_kiosk_table_name

# DNA API Configuration
DNA_BASE_URL=your_dna_api_url
DNA_USERNAME=your_dna_username
DNA_PASSWORD=your_dna_password

# MeridianLink API Configuration
ML_BASE_URL=your_meridianlink_api_url
ML_USERNAME=your_ml_username
ML_PASSWORD=your_ml_password
```

3. Run the application:
```bash
python app.py
```

The application will be available at `http://localhost:8082`

## Database Requirements

This application requires access to multiple database functions:
- `get_kiosk_queue()` - Get waiting/handled lists
- `get_kiosk_queue_count()` - Get waiting count
- `update_kiosk_queue_status()` - Mark entries as handled
- `get_facing_member_details()` - Get member details for viewing
- `get_current_visitor_count()` - For context processor

## Templates

Key templates located in the `templates/` directory:
- `kiosk_queue.html` - Main queue management interface
- `member_details.html` - Detailed member information view
- `layout_advanced.html` - Base layout template

## Static Assets

- `static/logo.png` - Credit union logo
- `static/css/theme.css` - Application styling

## API Integrations

- **DNA API**: Member data and transaction history
- **MeridianLink API**: Loan information
- **Insight Generator**: AI-powered member insights

## Caching System

The application uses TTL caches for performance:
- DNA data cache (1 hour TTL)
- Transaction cache (10 minutes TTL)
- Insights cache (10 minutes TTL)

## Background Processing

- Automatic pre-fetching of DNA data and transactions for waiting members
- Background insight generation
- Threaded operations for improved performance

## Features

### Queue Management
- View members waiting for assistance
- Mark entries as handled
- Real-time queue count display

### Member Details
- Comprehensive member information from DNA
- Account details and balances
- Recent transaction history
- Loan information from MeridianLink
- AI-generated insights

### Performance Optimizations
- Background data pre-fetching
- Intelligent caching
- Asynchronous processing

## Logging

Application logs are written to `logs/waiting_app.log` with rotation.

## Error Handling

The application gracefully handles:
- Database connection issues
- API unavailability
- Missing member data
- Network timeouts
