terraform {
  required_version = ">= 1.8"

  required_providers {
    postgresql = {
      source  = "cyrilgdn/postgresql"
      version = ">= 1.22"
    }
  }
}

provider "postgresql" {
  host     = var.db_host
  port     = var.db_port
  username = var.db_admin_user
  password = var.db_admin_password
  sslmode  = var.db_sslmode
}