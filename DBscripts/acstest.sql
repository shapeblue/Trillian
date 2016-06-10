-- --------------------------------------------------------
-- Host:                         10.2.0.3
-- Server version:               5.5.44-MariaDB - MariaDB Server
-- Server OS:                    Linux
-- HeidiSQL Version:             9.2.0.4947
-- --------------------------------------------------------

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8mb4 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;

-- Dumping database structure for acstest
CREATE DATABASE IF NOT EXISTS `acstest` /*!40100 DEFAULT CHARACTER SET latin1 */;
USE `acstest`;


-- Dumping structure for table acstest.podnetworks
DROP TABLE IF EXISTS `podnetworks`;
CREATE TABLE IF NOT EXISTS `podnetworks` (
  `idpod` int(11) NOT NULL,
  `podstartip` varchar(45) DEFAULT NULL,
  `podendip` varchar(45) DEFAULT NULL,
  `podmask` varchar(45) DEFAULT NULL,
  `podgw` varchar(45) DEFAULT NULL,
  `numips` int(11) DEFAULT NULL,
  `vlans` varchar(45) DEFAULT NULL,
  `numvlans` varchar(45) DEFAULT NULL,
  `inuse` varchar(45) NOT NULL,
  `updated` datetime DEFAULT NULL,
  `comment` varchar(400) DEFAULT NULL,
  `environmentname` varchar(100) NOT NULL,
  PRIMARY KEY (`idpod`),
  UNIQUE KEY `idpod_UNIQUE` (`idpod`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- Dumping data for table acstest.podnetworks: ~20 rows (approximately)
/*!40000 ALTER TABLE `podnetworks` DISABLE KEYS */;
INSERT INTO `podnetworks` (`idpod`, `podstartip`, `podendip`, `podmask`, `podgw`, `numips`, `vlans`, `numvlans`, `inuse`, `updated`, `comment`, `environmentname`) VALUES
	(1, '10.11.10.1', '10.11.10.20', '255.255.0.0', '10.11.254.254', 20, '501-520', '20', 'TRUE', '2016-04-25 17:33:59', 'kvmzone', 'kvmtest1'),
	(2, '10.11.10.21', '10.11.10.40', '255.255.0.0', '10.11.254.254', 20, '521-540', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(3, '10.11.10.41', '10.11.10.60', '255.255.0.0', '10.11.254.254', 20, '541-560', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(4, '10.11.10.61', '10.11.10.80', '255.255.0.0', '10.11.254.254', 20, '561-580', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(5, '10.11.10.81', '10.11.10.11', '255.255.0.0', '10.11.254.254', 20, '581-600', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(6, '10.11.10.101', '10.11.10.120', '255.255.0.0', '10.11.254.254', 20, '601-620', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(7, '10.11.10.121', '10.11.10.140', '255.255.0.0', '10.11.254.254', 20, '621-640', '20', 'FALSE', '2016-03-04 08:20:46', 'N/A', ''),
	(8, '10.11.10.141', '10.11.10.160', '255.255.0.0', '10.11.254.254', 20, '641-660', '20', 'FALSE', '2016-03-04 19:03:35', 'N/A', ''),
	(9, '10.11.10.161', '10.11.10.180', '255.255.0.0', '10.11.254.254', 20, '661-680', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(10, '10.11.10.181', '10.11.10.200', '255.255.0.0', '10.11.254.254', 20, '681-700', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(11, '10.11.10.201', '10.11.10.220', '255.255.0.0', '10.11.254.254', 20, '701-720', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(12, '10.11.10.221', '10.11.10.240', '255.255.0.0', '10.11.254.254', 20, '721-740', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(13, '10.11.11.1', '10.11.11.20', '255.255.0.0', '10.11.254.254', 20, '741-760', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(14, '10.11.11.21', '10.11.11.40', '255.255.0.0', '10.11.254.254', 20, '761-780', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(15, '10.11.11.41', '10.11.11.60', '255.255.0.0', '10.11.254.254', 20, '781-800', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(16, '10.11.11.61', '10.11.11.80', '255.255.0.0', '10.11.254.254', 20, '801-820', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(17, '10.11.11.81', '10.11.11.100', '255.255.0.0', '10.11.254.254', 20, '821-840', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(18, '10.11.11.101', '10.11.11.120', '255.255.0.0', '10.11.254.254', 20, '841-860', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(19, '10.11.11.121', '10.11.11.140', '255.255.0.0', '10.11.254.254', 20, '861-880', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(20, '10.11.11.141', '10.11.11.160', '255.255.0.0', '10.11.254.254', 20, '881-900', '20', 'FALSE', '2016-01-07 16:18:55', 'N/A', '');
/*!40000 ALTER TABLE `podnetworks` ENABLE KEYS */;


-- Dumping structure for table acstest.primarystorage
DROP TABLE IF EXISTS `primarystorage`;
CREATE TABLE IF NOT EXISTS `primarystorage` (
  `idpri` int(11) NOT NULL,
  `protocol` varchar(45) DEFAULT NULL,
  `host` varchar(45) DEFAULT NULL,
  `path` varchar(90) DEFAULT NULL,
  `inuse` varchar(45) NOT NULL,
  `updated` datetime DEFAULT NULL,
  `comment` varchar(400) DEFAULT NULL,
  `environmentname` varchar(100) NOT NULL,
  PRIMARY KEY (`idpri`),
  UNIQUE KEY `idstorage_UNIQUE` (`idpri`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- Dumping data for table acstest.primarystorage: ~20 rows (approximately)
/*!40000 ALTER TABLE `primarystorage` DISABLE KEYS */;
INSERT INTO `primarystorage` (`idpri`, `protocol`, `host`, `path`, `inuse`, `updated`, `comment`, `environmentname`) VALUES
	(1, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri1', 'TRUE', '2016-04-25 17:33:59', 'kvmzone', 'kvmtest1'),
	(2, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri2', 'TRUE', '2016-01-07 16:18:55', 'N/A', 'kvmtest1'),
	(3, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri3', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(4, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri4', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(5, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri5', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(6, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri6', 'FALSE', '2016-01-07 16:18:55', 'N/A', 'N/A'),
	(7, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri7', 'FALSE', '2016-03-04 08:20:46', 'N/A', ''),
	(8, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri8', 'FALSE', '2016-03-04 19:03:35', 'N/A', ''),
	(9, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri9', 'FALSE', '2016-01-07 16:18:55', 'N/A', 'N/A'),
	(10, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri10', 'FALSE', '2016-01-07 16:18:55', 'N/A', 'N/A'),
	(11, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri11', 'FALSE', '2016-01-07 16:18:55', 'N/A', 'N/A'),
	(12, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri12', 'FALSE', '2016-01-07 16:18:55', 'N/A', 'N/A'),
	(13, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri13', 'FALSE', '2016-01-07 16:18:55', 'N/A', 'N/A'),
	(14, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri14', 'FALSE', '2016-01-07 16:18:55', 'N/A', 'N/A'),
	(15, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri15', 'FALSE', '2016-01-07 16:18:55', 'N/A', 'N/A'),
	(16, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri16', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(17, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri17', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(18, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri18', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(19, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri19', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(20, 'nfs', '10.0.1.30', '/acs/primary/gw1/pri20', 'FALSE', '2016-01-07 16:18:55', 'N/A', '');
/*!40000 ALTER TABLE `primarystorage` ENABLE KEYS */;


-- Dumping structure for table acstest.pubnetworks
DROP TABLE IF EXISTS `pubnetworks`;
CREATE TABLE IF NOT EXISTS `pubnetworks` (
  `idpub` int(11) NOT NULL,
  `pubstartip` varchar(45) DEFAULT NULL,
  `pubendip` varchar(45) DEFAULT NULL,
  `pubmask` varchar(45) DEFAULT NULL,
  `pubgw` varchar(45) DEFAULT NULL,
  `numips` int(11) DEFAULT NULL,
  `inuse` varchar(45) NOT NULL,
  `updated` datetime DEFAULT NULL,
  `comment` varchar(400) DEFAULT NULL,
  `environmentname` varchar(100) NOT NULL,
  PRIMARY KEY (`idpub`),
  UNIQUE KEY `idub_UNIQUE` (`idpub`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- Dumping data for table acstest.pubnetworks: ~20 rows (approximately)
/*!40000 ALTER TABLE `pubnetworks` DISABLE KEYS */;
INSERT INTO `pubnetworks` (`idpub`, `pubstartip`, `pubendip`, `pubmask`, `pubgw`, `numips`, `inuse`, `updated`, `comment`, `environmentname`) VALUES
	(1, '10.101.1.1', '10.101.1.20', '255.255.240.0', '10.101.15.254', 20, 'TRUE', '2016-04-25 17:33:59', 'kvmzone', 'kvmtest1'),
	(2, '10.101.1.21', '10.101.1.40', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(3, '10.101.1.41', '10.101.1.60', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(4, '10.101.1.61', '10.101.1.80', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(5, '10.101.1.81', '10.101.1.100', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(6, '10.101.1.101', '10.101.1.120', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(7, '10.101.1.121', '10.101.1.140', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-03-04 08:20:46', 'N/A', ''),
	(8, '10.101.1.141', '10.101.1.160', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-03-04 19:03:35', 'N/A', ''),
	(9, '10.101.1.161', '10.101.1.180', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(10, '10.101.1.181', '10.101.1.200', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(11, '10.101.1.201', '10.101.1.220', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(12, '10.101.1.221', '10.101.1.240', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(13, '10.101.2.1', '10.101.2.20', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(14, '10.101.2.21', '10.101.2.40', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(15, '10.101.2.41', '10.101.2.60', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(16, '10.101.2.61', '10.101.2.80', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(17, '10.101.2.81', '10.101.2.100', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(18, '10.101.2.101', '10.101.2.120', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(19, '10.101.2.121', '10.101.2.140', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(20, '10.101.2.141', '10.101.2.160', '255.255.240.0', '10.101.15.254', 20, 'FALSE', '2016-01-07 16:18:55', 'N/A', '');
/*!40000 ALTER TABLE `pubnetworks` ENABLE KEYS */;


-- Dumping structure for table acstest.secondarystorage
DROP TABLE IF EXISTS `secondarystorage`;
CREATE TABLE IF NOT EXISTS `secondarystorage` (
  `idsec` int(11) NOT NULL,
  `protocol` varchar(45) DEFAULT NULL,
  `host` varchar(45) DEFAULT NULL,
  `path` varchar(90) DEFAULT NULL,
  `inuse` varchar(45) NOT NULL,
  `updated` datetime DEFAULT NULL,
  `comment` varchar(400) DEFAULT NULL,
  `environmentname` varchar(100) NOT NULL,
  PRIMARY KEY (`idsec`),
  UNIQUE KEY `idstorage_UNIQUE` (`idsec`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- Dumping data for table acstest.secondarystorage: ~20 rows (approximately)
/*!40000 ALTER TABLE `secondarystorage` DISABLE KEYS */;
INSERT INTO `secondarystorage` (`idsec`, `protocol`, `host`, `path`, `inuse`, `updated`, `comment`, `environmentname`) VALUES
	(1, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec1', 'TRUE', '2016-04-25 17:33:59', 'kvmzone', 'kvmtest1'),
	(2, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec2', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(3, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec3', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(4, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec4', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(5, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec5', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(6, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec6', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(7, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec7', 'FALSE', '2016-03-04 08:20:46', 'N/A', ''),
	(8, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec8', 'FALSE', '2016-03-04 19:03:35', 'N/A', ''),
	(9, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec9', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(10, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec10', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(11, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec11', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(12, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec12', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(13, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec13', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(14, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec14', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(15, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec15', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(16, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec16', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(17, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec17', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(18, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec18', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(19, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec19', 'FALSE', '2016-01-07 16:18:55', 'N/A', ''),
	(20, 'nfs', '10.0.1.30', '/acs/secondary/gw1/sec20', 'FALSE', '2016-01-07 16:18:55', 'N/A', '');
/*!40000 ALTER TABLE `secondarystorage` ENABLE KEYS */;
/*!40101 SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IF(@OLD_FOREIGN_KEY_CHECKS IS NULL, 1, @OLD_FOREIGN_KEY_CHECKS) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
