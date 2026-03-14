SELECT 'CREATE DATABASE kalba_test' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'kalba_test')\gexec
