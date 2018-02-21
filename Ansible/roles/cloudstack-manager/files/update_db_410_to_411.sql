use cloud;

CREATE TABLE IF NOT EXISTS `cloud`.`netscaler_servicepackages` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'id',
  `uuid` varchar(255) UNIQUE,
  `name` varchar(255) UNIQUE COMMENT 'name of the service package',
  `description` varchar(255) COMMENT 'description of the service package',
  PRIMARY KEY  (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;


CREATE TABLE IF NOT EXISTS `cloud`.`external_netscaler_controlcenter` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'id',
  `uuid` varchar(255) UNIQUE,
  `username` varchar(255) COMMENT 'username of the NCC',
  `password` varchar(255) COMMENT 'password of NCC',
  `ncc_ip` varchar(255) COMMENT 'IP of NCC Manager',
  `num_retries` bigint unsigned NOT NULL default 2 COMMENT 'Number of retries in
ncc for command failure',
  PRIMARY KEY  (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;


ALTER TABLE `cloud`.`sslcerts` ADD COLUMN `name` varchar(255) NULL default NULL
COMMENT 'Name of the Certificate';
ALTER TABLE `cloud`.`network_offerings` ADD COLUMN `service_package_id`
varchar(255) NULL default NULL COMMENT 'Netscaler ControlCenter Service
Package';


DROP VIEW IF EXISTS `cloud`.`user_view`;
CREATE VIEW `cloud`.`user_view` AS
    select
        user.id,
        user.uuid,
        user.username,
        user.password,
        user.firstname,
        user.lastname,
        user.email,
        user.state,
        user.api_key,
        user.secret_key,
        user.created,
        user.removed,
        user.timezone,
        user.registration_token,
        user.is_registered,
        user.incorrect_login_attempts,
        user.source,
        user.default,
        account.id account_id,
        account.uuid account_uuid,
        account.account_name account_name,
        account.type account_type,
        account.role_id account_role_id,
        domain.id domain_id,
        domain.uuid domain_uuid,
        domain.name domain_name,
        domain.path domain_path,
        async_job.id job_id,
        async_job.uuid job_uuid,
        async_job.job_status job_status,
        async_job.account_id job_account_id
    from
        `cloud`.`user`
            inner join
        `cloud`.`account` ON user.account_id = account.id
            inner join
        `cloud`.`domain` ON account.domain_id = domain.id
            left join
        `cloud`.`async_job` ON async_job.instance_id = user.id
            and async_job.instance_type = 'User'
            and async_job.job_status = 0;

