-- MySQL dump 10.14  Distrib 5.5.44-MariaDB, for Linux (x86_64)
--
-- Host: localhost    Database: trillian_envs
-- ------------------------------------------------------
-- Server version	5.5.44-MariaDB

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Current Database: `trillian_envs`
--

CREATE DATABASE /*!32312 IF NOT EXISTS*/ `trillian_envs` /*!40100 DEFAULT CHARACTER SET latin1 */;

USE `trillian_envs`;

--
-- Table structure for table `environments`
--

DROP TABLE IF EXISTS `environments`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `environments` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(45) DEFAULT NULL,
  `envuuid` varchar(45) DEFAULT NULL,
  `comment` varchar(120) DEFAULT NULL,
  `created` varchar(45) DEFAULT NULL,
  `removed` varchar(45) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `id_UNIQUE` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=latin1;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `environments`
--

LOCK TABLES `environments` WRITE;
/*!40000 ALTER TABLE `environments` DISABLE KEYS */;
/*!40000 ALTER TABLE `environments` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `podnetworks`
--

DROP TABLE IF EXISTS `podnetworks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `podnetworks` (
  `idpod` int(11) NOT NULL,
  `podstartip` varchar(45) DEFAULT NULL,
  `podendip` varchar(45) DEFAULT NULL,
  `podmask` varchar(45) DEFAULT NULL,
  `podgw` varchar(45) DEFAULT NULL,
  `numips` int(11) DEFAULT NULL,
  `vlans` varchar(45) DEFAULT NULL,
  `numvlans` varchar(45) DEFAULT NULL,
  `inuse` varchar(45) NOT NULL,
  `envid` int(11) DEFAULT NULL,
  `updated` datetime DEFAULT NULL,
  `removed` datetime DEFAULT NULL,
  `comment` varchar(400) DEFAULT NULL,
  `environmentname` varchar(100) NOT NULL,
  PRIMARY KEY (`idpod`),
  UNIQUE KEY `idpod_UNIQUE` (`idpod`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `podnetworks`
--

LOCK TABLES `podnetworks` WRITE;
/*!40000 ALTER TABLE `podnetworks` DISABLE KEYS */;
INSERT INTO `podnetworks` VALUES (1,'10.2.5.1','10.2.5.20','255.255.0.0','10.2.254.254',20,'501-520','20','FALSE',NULL,NULL,NULL,'',''),(2,'10.2.5.21','10.2.5.40','255.255.0.0','10.2.254.254',20,'521-540','20','FALSE',NULL,NULL,NULL,'',''),(3,'10.2.5.41','10.2.5.60','255.255.0.0','10.2.254.254',20,'541-560','20','FALSE',NULL,NULL,NULL,'',''),(4,'10.2.5.61','10.2.5.80','255.255.0.0','10.2.254.254',20,'561-580','20','FALSE',NULL,NULL,NULL,'',''),(5,'10.2.5.81','10.2.5.100','255.255.0.0','10.2.254.254',20,'581-600','20','FALSE',NULL,NULL,NULL,'',''),(6,'10.2.5.101','10.2.5.120','255.255.0.0','10.2.254.254',20,'601-620','20','FALSE',NULL,NULL,NULL,'',''),(7,'10.2.5.121','10.2.5.140','255.255.0.0','10.2.254.254',20,'621-640','20','FALSE',NULL,NULL,NULL,'',''),(8,'10.2.5.141','10.2.5.160','255.255.0.0','10.2.254.254',20,'641-660','20','FALSE',NULL,NULL,NULL,'',''),(9,'10.2.5.161','10.2.5.180','255.255.0.0','10.2.254.254',20,'661-680','20','FALSE',NULL,NULL,NULL,'',''),(10,'10.2.5.181','10.2.5.200','255.255.0.0','10.2.254.254',20,'681-700','20','FALSE',NULL,NULL,NULL,'',''),(11,'10.2.5.201','10.2.5.220','255.255.0.0','10.2.254.254',20,'701-720','20','FALSE',NULL,NULL,NULL,'',''),(12,'10.2.5.221','10.2.5.240','255.255.0.0','10.2.254.254',20,'721-740','20','FALSE',NULL,NULL,NULL,'',''),(13,'10.2.6.1','10.2.6.20','255.255.0.0','10.2.254.254',20,'741-760','20','FALSE',NULL,NULL,NULL,'',''),(14,'10.2.6.21','10.2.6.40','255.255.0.0','10.2.254.254',20,'761-780','20','FALSE',NULL,NULL,NULL,'',''),(15,'10.2.6.41','10.2.6.60','255.255.0.0','10.2.254.254',20,'781-800','20','FALSE',NULL,NULL,NULL,'',''),(16,'10.2.6.61','10.2.6.80','255.255.0.0','10.2.254.254',20,'801-820','20','FALSE',NULL,NULL,NULL,'',''),(17,'10.2.6.81','10.2.6.100','255.255.0.0','10.2.254.254',20,'821-840','20','FALSE',NULL,NULL,NULL,'',''),(18,'10.2.6.101','10.2.6.120','255.255.0.0','10.2.254.254',20,'841-860','20','FALSE',NULL,NULL,NULL,'',''),(19,'10.2.6.121','10.2.6.140','255.255.0.0','10.2.254.254',20,'861-880','20','FALSE',NULL,NULL,NULL,'',''),(20,'10.2.6.141','10.2.6.160','255.255.0.0','10.2.254.254',20,'881-900','20','FALSE',NULL,NULL,NULL,'','');
/*!40000 ALTER TABLE `podnetworks` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `pubnetworks`
--

DROP TABLE IF EXISTS `pubnetworks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `pubnetworks` (
  `idpub` int(11) NOT NULL,
  `pubstartip` varchar(45) DEFAULT NULL,
  `pubendip` varchar(45) DEFAULT NULL,
  `pubmask` varchar(45) DEFAULT NULL,
  `pubgw` varchar(45) DEFAULT NULL,
  `numips` int(11) DEFAULT NULL,
  `vlan` varchar(45) DEFAULT NULL,
  `inuse` varchar(45) NOT NULL,
  `envid` int(11) DEFAULT NULL,
  `updated` datetime DEFAULT NULL,
  `removed` datetime DEFAULT NULL,
  `comment` varchar(400) DEFAULT NULL,
  `environmentname` varchar(100) NOT NULL,
  PRIMARY KEY (`idpub`),
  UNIQUE KEY `idub_UNIQUE` (`idpub`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `pubnetworks`
--

LOCK TABLES `pubnetworks` WRITE;
/*!40000 ALTER TABLE `pubnetworks` DISABLE KEYS */;
INSERT INTO `pubnetworks` VALUES (1,'10.1.34.1','10.1.34.20','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(2,'10.1.34.21','10.1.34.40','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(3,'10.1.34.41','10.1.34.60','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(4,'10.1.34.61','10.1.34.80','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(5,'10.1.34.81','10.1.34.100','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(6,'10.1.34.101','10.1.34.120','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(7,'10.1.34.121','10.1.34.140','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(8,'10.1.34.141','10.1.34.160','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(9,'10.1.34.161','10.1.34.180','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(10,'10.1.34.181','10.1.34.200','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(11,'10.1.34.201','10.1.34.220','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(12,'10.1.34.221','10.1.34.240','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(13,'10.1.35.1','10.1.35.20','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(14,'10.1.35.21','10.1.35.40','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(15,'10.1.35.41','10.1.35.60','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(16,'10.1.35.61','10.1.35.80','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(17,'10.1.35.81','10.1.35.100','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(18,'10.1.35.101','10.1.35.120','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(19,'10.1.35.121','10.1.35.140','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'',''),(20,'10.1.35.141','10.1.35.160','255.255.224.0','10.1.63.254',20,'1000','FALSE',NULL,NULL,NULL,'','');
/*!40000 ALTER TABLE `pubnetworks` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2016-07-13 10:38:56
