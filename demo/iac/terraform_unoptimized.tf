provider "aws" {
  region = "us-east-1"
}

resource "aws_instance" "app_server" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "m5.large"

  tags = {
    Name = "client-demo-app"
  }
}

resource "aws_ebs_volume" "data" {
  availability_zone = "us-east-1a"
  size              = 500
  volume_type       = "gp2"
}

resource "aws_db_instance" "app_db" {
  identifier             = "client-demo-dev-db"
  engine                 = "postgres"
  instance_class         = "db.m5.large"
  allocated_storage      = 200
  multi_az               = true
  publicly_accessible    = false
  skip_final_snapshot    = true
  backup_retention_period = 0
}

resource "aws_s3_bucket" "logs_bucket" {
  bucket = "finops-client-demo-logs-bucket"
}
