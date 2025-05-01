# Rotato 🌀

Rotato is a purpose-built microSaaS that solves one specific problem exceptionally well: generating non-repeating paired combinations from a list of participants. Perfect for study buddies, code reviews, mentorship programs, and any situation where you need to ensure everyone gets paired with everyone else.

## Features

### Core Functionality
- Create rooms with participants
- Generate random, non-repeating pairings
- Permanent room URLs for easy access
- Complete pairing history tracking

### Premium Features
- Unlimited participants per room (free tier limited to 10)
- Slack integration for automatic notifications
- Scheduled automatic pairing generation
- Priority support

## Tech Stack

Rotato is built with a deliberately simple and maintainable stack:

- **Backend**: Flask (Python)
- **Database**: SQLite (with easy migration path to larger DBs)
- **Authentication**: Flask-Login
- **Payment Processing**: Stripe
- **Job Scheduling**: APScheduler
- **Frontend**: Vanilla JS with minimal dependencies

## Getting Started

### Prerequisites

- Python 3.8+
- pip

### Installation

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/rotato.git
   cd rotato
   ```

2. Create and activate a virtual environment:
   ```
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   ```
   cp .env.example .env
   ```
   Edit the .env file with your configuration values.

5. Run the application:
   ```
   python app.py
   ```

6. Visit `http://localhost:5000` in your browser to start using Rotato.

## Development

### Database Schema

Rotato uses SQLite with the following main tables:

- **users**: User accounts and subscription information
- **rooms**: Pairing rooms with participant lists and history
- **jobs**: Scheduled automatic pairing jobs

### Project Structure

```
rotato/
├── app.py             # Main application file
├── pairing.py         # Pairing algorithms
├── rotato.db          # SQLite database
├── requirements.txt   # Dependencies
├── static/            # CSS and static assets
└── templates/         # HTML templates
```

### Key Components

1. **Pairing Algorithm**: Located in `pairing.py`, this is the core logic for generating random, non-repeating pairs.

2. **Authentication**: User management with secure password hashing via bcrypt.

3. **Subscription Logic**: Integration with Stripe for payment processing.

4. **Scheduling System**: Using APScheduler to handle automatic pair generation at specified times.

5. **Slack Integration**: Webhook-based notifications when new pairs are generated.

## Deployment

### Heroku Deployment

1. Create a Heroku account and install the Heroku CLI
2. Initialize a git repository if not already done
3. Create a Heroku app:
   ```
   heroku create yourapppname
   ```
4. Set environment variables:
   ```
   heroku config:set FLASK_SECRET_KEY=your_secret_key
   heroku config:set STRIPE_SECRET_KEY=your_stripe_key
   # Add other env vars as needed
   ```
5. Deploy:
   ```
   git push heroku main
   ```

### Docker Deployment

A Dockerfile is provided for containerized deployment. Build and run with:

```
docker build -t rotato .
docker run -p 5000:5000 rotato
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgements

- Flask team for the excellent web framework
- Stripe for payment processing
- All open source projects that made this possible

## Contact

For support or inquiries, reach out at hello@rotato.app
