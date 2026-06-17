# Cardinal ETLs

Automated ETL system for processing Cardinal Healthcare invoice data and other related data pipelines.

## 🎯 Overview

Cardinal ETLs is a comprehensive data processing system that automates the extraction, transformation, and loading of Cardinal Healthcare invoice data into the PRIME database. The system includes robust authentication, error handling, email notifications, and automated deployment capabilities.

## 📋 Components

### Core ETL Scripts
- **`Cardinal_Inv_Upload.py`** - Main ETL process for Cardinal invoice data

### Infrastructure
- **`run_with_impersonation.py`** - Centralized Windows impersonation wrapper
- **`windows_impersonation.py`** - Windows authentication utilities
- **`msgraph_email.py`** - Microsoft Graph API email notifications

### Test Scripts
- **`tests/test_network_drive.py`** - Network connectivity testing
- **`tests/test_prime_connection.py`** - Database connection validation
- **`tests/test_email_notification.py`** - Email system verification

### Setup & Configuration
- **`config.yaml`** - System configuration settings
- **`requirements.txt`** - Python dependencies

## 🚀 Quick Start

### Run ETL Process
```bat
run.bat
```

`run.bat` creates the local virtual environment if needed, installs packages
from `requirements.txt`, verifies `.env` and `config.yaml` exist, and writes
runtime output to `logs\python_run.log`.

## 🔧 System Requirements

- **OS**: Windows Server 2016+ or Windows 10/11
- **Python**: 3.8+
- **Database**: SQL Server with Windows Authentication
- **Network**: Access to `\\montefiore.org` file shares
- **Permissions**: Microsoft Graph API for email notifications

## 🏗️ Architecture

### Centralized Impersonation
All scripts use the centralized `run_with_impersonation.py` wrapper for consistent Windows authentication using service account credentials.

### Configuration-Driven
System settings are managed through `config.yaml` for easy environment-specific customization.

## 📊 Monitoring

- **Health Status Logging**: All ETL runs are logged to `[PRIME].[dbo].[ETL_Health_Status]`
- **Email Notifications**: Automatic success/failure notifications via Microsoft Graph
- **Detailed Logging**: Comprehensive logs stored in `logs/` directory

## 🛠️ Development

### Running Tests
```powershell
# Network connectivity test
python run_with_impersonation.py tests/test_network_drive.py

# Database connection test  
python run_with_impersonation.py tests/test_prime_connection.py

# Email system test
python run_with_impersonation.py tests/test_email_notification.py
```

### Direct Script Execution
Scripts can be run directly as the current user for development/testing when you have the necessary permissions:

```powershell
python tests/test_network_drive.py
python tests/test_prime_connection.py
python Cardinal_Inv_Upload.py
```

## 📝 Configuration

Key configuration files:
- **`.env`** - Service account and Microsoft Graph credentials
- **`config.yaml`** - Database, network, and email settings
- **`requirements.txt`** - Python package dependencies

## 🔐 Security

- Windows impersonation for secure service account usage
- Comprehensive audit logging

## 📧 Email Notifications

The system sends automated notifications for:
- Successful ETL completions with processing statistics
- Error conditions with detailed logs
- System health status updates

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📜 License

This project is internal to Montefiore Health System.

## 🆘 Support

For technical support or questions, contact the Data Analytics team.
