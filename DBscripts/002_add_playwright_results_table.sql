-- Migration: Add pr_playwright_results table for UI test results
-- Date: 2026-02-10
-- Purpose: Track Playwright UI test results for CloudStack PRs

-- Create pr_playwright_results table
CREATE TABLE IF NOT EXISTS pr_playwright_results (
  id INT PRIMARY KEY AUTO_INCREMENT,
  
  -- PR Information
  pr_number INT NOT NULL,
  pr_title VARCHAR(500),
  
  -- Test Execution Info
  test_suite VARCHAR(100) DEFAULT 'ui-tests',  -- For future: login, dashboard, instances, etc.
  total_tests INT NOT NULL,
  passed_tests INT NOT NULL,
  failed_tests INT NOT NULL,
  skipped_tests INT DEFAULT 0,
  
  -- Test Details
  duration_ms INT,                              -- Total test duration in milliseconds
  browser VARCHAR(50) DEFAULT 'chromium',       -- chromium, firefox, webkit
  failed_test_names TEXT,                       -- Comma-separated list of failed test names
  
  -- Artifacts
  logs_url VARCHAR(500),                        -- Link to Jenkins HTML report or artifact storage
  screenshot_count INT DEFAULT 0,               -- Number of screenshots generated
  video_count INT DEFAULT 0,                    -- Number of videos generated
  
  -- Build Info
  jenkins_build_number INT,                     -- Jenkins build that ran these tests
  jenkins_job_name VARCHAR(200),                -- Jenkins job name
  trillian_env_id VARCHAR(100),                 -- Trillian environment ID (if applicable)
  
  -- Timestamps
  test_started_at DATETIME,                     -- When tests started
  test_completed_at DATETIME NOT NULL,          -- When tests completed
  inserted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  
  -- Indexes for performance
  INDEX idx_pr_number (pr_number),
  INDEX idx_test_completed (test_completed_at),
  INDEX idx_jenkins_build (jenkins_build_number),
  INDEX idx_test_suite (test_suite)
  
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Verify table was created
SELECT 
  'Table created successfully' AS status,
  COUNT(*) as column_count
FROM information_schema.columns 
WHERE table_schema = DATABASE()
AND table_name = 'pr_playwright_results';
