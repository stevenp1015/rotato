# Changelog

All notable changes to Rotato will be documented in this file.

## [1.0.0] - 2025-05-01

### Added
- Complete authentication system with registration and login
- User dashboard for managing rooms
- Premium subscription integration with Stripe
- Feature-gating for premium features (unlimited participants, scheduling, Slack)
- Slack webhook integration for pair notifications
- Automatic scheduling of pair generation
- Room settings page for configuration
- Responsive UI with modern glass-like design
- Docker support for containerized deployment
- Deployment script for server setup
- Comprehensive documentation

### Changed
- Rearchitected database schema to support users and ownership
- Enhanced pairing algorithm for better randomization
- Improved UI/UX with more intuitive design

### Technical Improvements
- Added SQLAlchemy for more robust database interactions
- Implemented APScheduler for background tasks
- Added bcrypt for secure password hashing
- Created configuration system with .env support
- Added appropriate error handling and flash messages
- Improved form validation with Flask-WTF
