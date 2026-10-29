/* ===========================================================================
   ss_esim  --  SQL Server mapping seed
   ---------------------------------------------------------------------------
   ใช้คู่กับชุด test data ที่  module\blendata\ss_esim\testdata\PGZ_ESIM_INVENTORY1_*.txt

   DDL, view definition และข้อมูลทั้งหมดในไฟล์นี้ ดึงมาจาก dev จริง
   environment dev (connection ดูที่ env-dev.md ที่ root ของโปรเจกต์) เมื่อ 2026-08-27
   ไม่ได้แต่งขึ้นเอง

   สิ่งที่สคริปต์นี้ทำ
     1. สร้าง schema dss_master ถ้ายังไม่มี
     2. สร้าง 3 ตาราง  tb_master_cdr_type / tb_service_profile / tb_service_bno_key
     3. สร้าง view vw_service_mapping_bno_key (ตัวที่ Blendata map เป็น
        ext_dss_vw_service_mapping_bno_key)
     4. insert ข้อมูล mapping ที่ชุดเทสต้องใช้
     5. verify

   สคริปต์นี้ IDEMPOTENT : รันซ้ำได้ ไม่ทับแถวที่มีอยู่แล้ว (ใช้ WHERE NOT EXISTS)
   ตาราง tb_master_cdr_type และ tb_service_profile มี IDENTITY จึงต้องใช้
   SET IDENTITY_INSERT เพื่อคง service_profile_runno ให้ตรงกับของจริง

   ---------------------------------------------------------------------------
   view กรอง 4 เงื่อนไข แถวจะโผล่ก็ต่อเมื่อผ่านครบ
       tb_service_profile.record_status    = 'A'
       tb_service_profile.wf_status        = 'AP'
       tb_service_profile.service_mkt_type = 'BNO'
       tb_service_bno_key.record_status    = 'A'
   และต้อง join ติดกันด้วย service_profile_runno (1:1)

   ---------------------------------------------------------------------------
   ผลที่ต้องได้หลังรัน : b_no ที่ขึ้นต้นด้วย %_ESIM_% ใน view = 8 แถว

     b_no                      inv_co  cp_id  service_id  effective    expired
     ECP_ESIM_Sales_Gable      AWN     10100  10000001    2024-01-01   2025-12-31
     ECP_ESIM_SalesT           AWN     10128  10000049    2025-01-16   (null)
     ECP_ESIM_ServiceT         AWN     10128  10000048    2025-01-16   (null)
     TEST_ESIM_TESTUPLOAD309   AWN     10205  10004150    2025-06-16   (null)
     TEST_ESIM_TESTUPLOAD310   AWN     10205  10004151    2025-06-16   (null)
     TEST_ESIM_TESTUPLOAD311   AWN     10205  10004152    2025-06-16   (null)
     TEST_ESIM_TESTUPLOAD312   AWN     10205  10004153    2025-06-16   (null)
     TEST_ESIM_TESTUPLOAD321   AWN     10205  10004149    2025-06-16   (null)

   บวก negative control อีก 3 แถวที่ตั้งใจให้ "ตกจาก view"
     ECP_ESIM_Service    bno_key.record_status = 'D'
     ECP_ESIM_SalesSAP   profile.service_mkt_type = 'USC'
     ECP_ESIM_Step2      ไม่มีแถวใน tb_service_profile (orphan)

   ---------------------------------------------------------------------------
   *** ห้ามเพิ่ม b_no 'ECP_ESIM_Step' ***
   ตั้งใจให้ไม่มี เพื่อให้เคส UNMAP U01-U03 ในไฟล์เทสทำงาน
   (sim_type 'Step' เคยใช้จริงและมีข้อมูลใน tb_transaction_ss_esim_valid 12 แถว
    แต่ mapping ถูกถอดออกไปแล้ว - เป็นสถานการณ์จริงที่อยากทดสอบ)

   ---------------------------------------------------------------------------
   เคสในไฟล์เทสกับ mapping ที่รองรับ

     เคส                          partner owner  sim_type      ผล
     MAP  M01-M10                 ECP     AWN    SalesT        เจอ mapping ครบ
     UNMAP U01-U03 ไม่มี mapping   ECP     AWN    Step          ไม่มี b_no นี้
     UNMAP U04-U06 owner ผิด       ECP     3BB    SalesT        mapping เป็นของ AWN
     UNMAP U07-U08 ก่อน effective  ECP     AWN    SalesT        first_installed 2024-01-01
     UNMAP U09-U10 หมดอายุ         ECP     AWN    Sales_Gable   expired 2025-12-31
   =========================================================================== */

-- USE [<database>];    -- << เปิดบรรทัดนี้ถ้าต้องการระบุ database เอง (ดูชื่อจาก env-*.md)
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

/* --- 1. SCHEMA ---------------------------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'dss_master')
    EXEC('CREATE SCHEMA [dss_master]');
GO

/* --- 2. TABLES ---------------------------------------------------------- */
IF OBJECT_ID('dss_master.tb_master_cdr_type','U') IS NULL
CREATE TABLE dss_master.[tb_master_cdr_type] (
    [cdr_type_runno]             int              IDENTITY(1,1) NOT NULL,
    [cdr_type]                   varchar(255)     NULL,
    [source_path]                varchar(255)     NULL,
    [data_table]                 varchar(255)     NULL,
    [record_status]              varchar(255)     NULL,
    CONSTRAINT [PK_tb_master_cdr_type] PRIMARY KEY CLUSTERED ([cdr_type_runno])
);
GO

IF OBJECT_ID('dss_master.tb_service_profile','U') IS NULL
CREATE TABLE dss_master.[tb_service_profile] (
    [service_id]                 int              NULL,
    [service_profile_runno]      int              IDENTITY(1,1) NOT NULL,
    [service_ref]                varchar(150)     NULL,
    [service_mkt_type]           varchar(5)       NULL,
    [network_type]               varchar(5)       NULL,
    [service_desc]               varchar(100)     NULL,
    [business_group]             int              NULL,
    [document_no]                varchar(250)     NULL,
    [share_basis]                varchar(8)       NULL,
    [check_payment]              varchar(1)       NULL,
    [invoicing_company_id]       varchar(10)      NULL,
    [settle_company]             varchar(10)      NULL,
    [content_partner_id]         varchar(20)      NULL,
    [settle_period]              varchar(10)      NULL,
    [service_group]              varchar(50)      NULL,
    [content_duplicate]          varchar(1)       NULL,
    [stand_alone]                varchar(1)       NULL,
    [package_type]               varchar(15)      NULL,
    [acc_package_type]           varchar(100)     NULL,
    [cost_center]                varchar(50)      NULL,
    [profit_center]              varchar(50)      NULL,
    [gl_code]                    varchar(50)      NULL,
    [gl_name]                    varchar(50)      NULL,
    [wbs]                        varchar(50)      NULL,
    [usage_rate]                 varchar(5)       NULL,
    [charging_unit]              varchar(10)      NULL,
    [price_rate_type]            varchar(8)       NULL,
    [price_rate]                 decimal(18,6)    NULL,
    [full_price]                 decimal(18,6)    NULL,
    [base_on_price]              decimal(18,6)    NULL,
    [discount_price_flag]        varchar(1)       NULL,
    [discount_price]             decimal(18,6)    NULL,
    [mkt_cost_sub]               decimal(18,6)    NULL,
    [service_period]             varchar(100)     NULL,
    [charging_type]              varchar(10)      NULL,
    [charging_value]             int              NULL,
    [is_cdr_zero_share]          varchar(1)       NULL,
    [minimum_guarantee]          varchar(1)       NULL,
    [unit_type]                  varchar(4)       NULL,
    [period]                     varchar(50)      NULL,
    [guarantee_effective_date]   datetime         NULL,
    [approve_by]                 varchar(100)     NULL,
    [approve_date]               datetime         NULL,
    [hard_service_status]        varchar(1)       NULL,
    [hold_service_status]        varchar(1)       NULL,
    [channel]                    varchar(10)      NULL,
    [service_id_ref]             varchar(50)      NULL,
    [reject_reason]              varchar(100)     NULL,
    [reject_reason_code]         varchar(4)       NULL,
    [reason_code]                varchar(10)      NULL,
    [checker]                    varchar(20)      NULL,
    [effective_date]             datetime         NULL,
    [expired_date]               datetime         NULL,
    [record_status]              varchar(50)      NULL,
    [wf_status]                  varchar(50)      NULL,
    [created_by]                 varchar(20)      NULL,
    [created_dt]                 datetime         NULL,
    [updated_by]                 varchar(20)      NULL,
    [updated_dt]                 datetime         NULL,
    [remark]                     varchar(50)      NULL,
    [mkt_absorb]                 varchar(1)       NULL,
    [business_group_sub]         varchar(50)      NULL,
    [ref_ee_id]                  varchar(50)      NULL,
    CONSTRAINT [PK_tb_service_profile] PRIMARY KEY CLUSTERED ([service_profile_runno])
);
GO

IF OBJECT_ID('dss_master.tb_service_bno_key','U') IS NULL
CREATE TABLE dss_master.[tb_service_bno_key] (
    [service_profile_runno]      int              NOT NULL,
    [bill_number]                varchar(50)      NULL,
    [service_bos_online]         varchar(50)      NULL,
    [service_desc]               varchar(50)      NULL,
    [record_status]              char(1)          NULL,
    [created_by]                 varchar(50)      NULL,
    [created_dt]                 datetime         NULL,
    [updated_by]                 varchar(50)      NULL,
    [updated_dt]                 datetime         NULL,
    [remark]                     varchar(100)     NULL,
    CONSTRAINT [PK_tb_service_bno_key] PRIMARY KEY CLUSTERED ([service_profile_runno])
);
GO

/* --- 3. VIEW ------------------------------------------------------------ */
IF OBJECT_ID('dss_master.vw_service_mapping_bno_key','V') IS NOT NULL
    DROP VIEW dss_master.vw_service_mapping_bno_key;
GO
CREATE     VIEW [dss_master].[vw_service_mapping_bno_key] AS SELECT
	dss_master.tb_service_profile.service_profile_runno,
	dss_master.tb_service_profile.service_mkt_type,
	dss_master.tb_service_profile.network_type,
	dss_master.tb_service_profile.service_desc,
	dss_master.tb_service_profile.settle_period,
	dss_master.tb_service_profile.invoicing_company_id,
	dss_master.tb_service_profile.service_group,
	dss_master.tb_service_profile.content_duplicate,
	dss_master.tb_service_profile.stand_alone,
	dss_master.tb_service_profile.package_type,
	dss_master.tb_service_profile.acc_package_type,
	dss_master.tb_service_profile.share_basis,
	dss_master.tb_service_profile.cost_center,
	dss_master.tb_service_profile.profit_center,
	dss_master.tb_service_profile.wbs,effective_date,
	dss_master.tb_service_profile.expired_date,
	dss_master.tb_service_profile.price_rate,
	dss_master.tb_service_profile.full_price,
	dss_master.tb_service_profile.base_on_price,
	dss_master.tb_service_profile.discount_price,
	dss_master.tb_service_profile.mkt_cost_sub,
	dss_master.tb_service_profile.price_rate_type,
	dss_master.tb_service_profile.charging_type,
	dss_master.tb_service_profile.charging_unit,
	dss_master.tb_service_profile.is_cdr_zero_share,
	dss_master.tb_service_profile.minimum_guarantee,
	dss_master.tb_service_profile.unit_type,
	dss_master.tb_service_profile.period,
	dss_master.tb_service_profile.guarantee_effective_date,
	dss_master.tb_service_profile.settle_company,
	dss_master.tb_service_profile.approve_by,
	dss_master.tb_service_profile.approve_date,
	dss_master.tb_service_profile.record_status,
	dss_master.tb_service_profile.wf_status,
	dss_master.tb_service_profile.created_by,
	dss_master.tb_service_profile.created_dt,
	dss_master.tb_service_profile.updated_by,
	dss_master.tb_service_profile.updated_dt,
	dss_master.tb_service_profile.remark,
	dss_master.tb_service_profile.content_partner_id,
	dss_master.tb_service_profile.hard_service_status,
	dss_master.tb_service_profile.hold_service_status,
	dss_master.tb_service_profile.service_id,
	dss_master.tb_service_profile.channel,
	dss_master.tb_service_profile.gl_code,
	dss_master.tb_service_profile.gl_name,
	dss_master.tb_service_bno_key.bill_number as b_no,
	dss_master.tb_service_bno_key.service_bos_online,
	dss_master.tb_service_bno_key.service_desc as service_desc_key,
	dss_master.tb_service_profile.service_period,
	dss_master.tb_service_profile.business_group,
	dss_master.tb_service_profile.business_group_sub 
FROM
	dss_master.tb_service_profile
	INNER JOIN
	dss_master.tb_service_bno_key
	ON 
		tb_service_profile.service_profile_runno = tb_service_bno_key.service_profile_runno
WHERE
	tb_service_profile.record_status = 'A' AND
	tb_service_profile.wf_status = 'AP' AND
	tb_service_profile.service_mkt_type = 'BNO' AND
	tb_service_bno_key.record_status = 'A' ;
GO

/* --- 4. SEED DATA ------------------------------------------------------- */
PRINT '-- seed dss_master.tb_master_cdr_type (1 rows)';
SET IDENTITY_INSERT dss_master.tb_master_cdr_type ON;
INSERT INTO dss_master.tb_master_cdr_type
    ([cdr_type_runno], [cdr_type], [source_path], [data_table], [record_status])
SELECT v.* FROM (VALUES
    (1, '1', 'file:/sources_dev/Phoenix/eSIM', 'ss_esim', 'A')
) v([cdr_type_runno], [cdr_type], [source_path], [data_table], [record_status])
WHERE NOT EXISTS (SELECT 1 FROM dss_master.tb_master_cdr_type x WHERE x.[cdr_type_runno] = v.[cdr_type_runno]);
SET IDENTITY_INSERT dss_master.tb_master_cdr_type OFF;
GO

PRINT '-- seed dss_master.tb_service_profile (10 rows)';
SET IDENTITY_INSERT dss_master.tb_service_profile ON;
INSERT INTO dss_master.tb_service_profile
    ([service_id], [service_profile_runno], [service_ref], [service_mkt_type], [network_type], [service_desc], [business_group], [document_no], [share_basis], [check_payment], [invoicing_company_id], [settle_company], [content_partner_id], [settle_period], [service_group], [content_duplicate], [stand_alone], [package_type], [acc_package_type], [cost_center], [profit_center], [gl_code], [gl_name], [wbs], [usage_rate], [charging_unit], [price_rate_type], [price_rate], [full_price], [base_on_price], [discount_price_flag], [discount_price], [mkt_cost_sub], [service_period], [charging_type], [charging_value], [is_cdr_zero_share], [minimum_guarantee], [unit_type], [period], [guarantee_effective_date], [approve_by], [approve_date], [hard_service_status], [hold_service_status], [channel], [service_id_ref], [reject_reason], [reject_reason_code], [reason_code], [checker], [effective_date], [expired_date], [record_status], [wf_status], [created_by], [created_dt], [updated_by], [updated_dt], [remark], [mkt_absorb], [business_group_sub], [ref_ee_id])
SELECT v.* FROM (VALUES
    (10000001, 10000001, '101000000000000000000000000000000000000ECP_ESIM_Sales', 'BNO', '3PP', 'ECP_ESIM_Sales', 4, 'Email : Benjaporn Krajangwongpaisan 19/10/2023 17:13   (??????? Price Rate ???????)', 'CSH', 'N', 'AWN', 'AWN', '10100', 'Monthly', NULL, 'N', NULL, 'S', 'ESS', NULL, NULL, NULL, NULL, NULL, 'CPR', NULL, NULL, 0.145000, 0.155150, NULL, 'N', NULL, NULL, 'M', NULL, NULL, 'Y', NULL, NULL, NULL, NULL, ' DSS_Migrate', '2024-01-01 00:00:00.000', NULL, NULL, 'DSS', NULL, NULL, NULL, NULL, ' DSS_Migrate', '2024-01-01 00:00:00.000', '2025-12-31 00:00:00.000', 'A', 'AP', ' DSS_Migrate', '2024-09-30 00:00:01.000', ' DSS_Migrate', '2024-09-30 00:00:01.000', '10000001', NULL, NULL, NULL),   -- 10000001 ECP_ESIM_Sales_Gable   -> อยู่ใน view | expired 2025-12-31 => เคส UNMAP U09/U10
    (10000002, 10000002, '1010000000000000000000000000000000000ECP_ESIM_Service', 'BNO', '3PP', 'ECP_ESIM_Service', 4, 'Email : Benjaporn Krajangwongpaisan 19/10/2023 17:13   (??????? Price Rate ???????)', 'CSH', 'N', 'AWN', 'AWN', '10100', 'Monthly', NULL, 'N', NULL, 'S', 'ESSV', NULL, NULL, NULL, NULL, NULL, 'CPR', NULL, NULL, 0.145000, 0.155150, NULL, 'N', NULL, NULL, 'M', NULL, NULL, 'Y', NULL, NULL, NULL, NULL, ' DSS_Migrate', '2024-01-01 00:00:00.000', NULL, NULL, 'DSS', NULL, NULL, NULL, NULL, ' DSS_Migrate', '2024-01-01 00:00:00.000', '2025-12-31 00:00:00.000', 'A', 'AP', ' DSS_Migrate', '2024-09-30 00:00:01.000', ' DSS_Migrate', '2024-09-30 00:00:01.000', '10000002', NULL, NULL, NULL),   -- 10000002 ECP_ESIM_Service       -> NEGATIVE: bno_key.record_status='D' จึงตกจาก view
    (10000048, 10000048, '10128000000000000000000000000000000000000000000160750', 'BNO', '3PP', '5G TOURIST eSIM 449B Call 1B/Min_WeSIM', 4, 'Email : Nina Charusilawong 08/01/2025 14:46,PLM25016633', 'CSH', 'N', 'AWN', 'MMT', '10128', 'Monthly', NULL, 'N', NULL, 'S', 'WSI', NULL, NULL, NULL, NULL, NULL, 'CPR', ' ', NULL, 419.630000, 449.004100, NULL, 'N', NULL, NULL, 'M', ' ', NULL, 'Y', 'N', NULL, NULL, NULL, 'pawatpor', NULL, NULL, NULL, 'DSS-UP', NULL, NULL, NULL, NULL, 'pawatpor', '2025-01-16 00:00:00.000', NULL, 'A', 'AP', 'pawatpor', '2025-01-14 11:05:02.210', 'pawatpor', '2025-01-21 18:31:07.630', NULL, NULL, NULL, NULL),   -- 10000048 ECP_ESIM_ServiceT      -> อยู่ใน view | active ไม่มีวันหมด
    (10000049, 10000049, '10128000000000000000000000000000000000000000000160752', 'BNO', '3PP', '5G TOURIST eSIM 699B Call 1B/Min_WeSIM', 4, 'Email : Nina Charusilawong 08/01/2025 14:46,PLM25016633', 'CSH', 'N', 'AWN', 'MMT', '10128', 'Monthly', NULL, 'N', NULL, 'S', 'WSI', NULL, NULL, NULL, NULL, NULL, 'CPR', ' ', NULL, 653.270000, 698.998900, NULL, 'N', NULL, NULL, 'M', ' ', NULL, 'Y', 'N', NULL, NULL, NULL, 'pawatpor', NULL, NULL, NULL, 'DSS-UP', NULL, NULL, NULL, NULL, 'pawatpor', '2025-01-16 00:00:00.000', NULL, 'A', 'AP', 'pawatpor', '2025-01-14 11:05:02.270', 'pawatpor', '2025-01-21 18:30:42.400', NULL, NULL, NULL, NULL),   -- 10000049 ECP_ESIM_SalesT        -> อยู่ใน view | *** ตัวหลักของเคส MAP *** + UNMAP U04-U08
    (10004017, 10004017, '10205000000000000000000000000000000000000003019007000', 'USC', '3PP', '4792605_ZNT', 2, 'USMAP144(3)/2568', 'CSH', 'N', 'AWN', 'AWN', '10205', 'Monthly', NULL, NULL, NULL, 'S', NULL, NULL, NULL, NULL, NULL, NULL, 'CPR', 'day', NULL, 2467.290000, 2640.000300, 0.000000, 'N', NULL, NULL, 'M', 'PTN', 0, 'Y', NULL, NULL, NULL, NULL, 'acharana', NULL, NULL, NULL, 'DSS', NULL, NULL, NULL, NULL, 'acharana', '2025-04-09 00:00:00.000', NULL, 'A', 'AP', 'pawatpor', '2025-04-10 11:45:14.163', 'acharana', '2025-04-10 15:18:35.547', NULL, 'N', 'GAMEON', NULL),   -- 10004017 ECP_ESIM_SalesSAP      -> NEGATIVE: service_mkt_type='USC' (ไม่ใช่ BNO) จึงตกจาก view
    (10004149, 10004149, '10205000000000000000000000000000000000PK2025061100082', 'BNO', '3PP', 'Ragnarok Origin Global_900 Nyan Berry', 2, 'PLM25068779', 'CSH', 'N', 'AWN', 'AWN', '10205', 'Monthly', NULL, 'N', NULL, 'S', ' ', NULL, NULL, NULL, NULL, NULL, 'CPR', ' ', NULL, 638.320000, 683.002400, NULL, 'N', NULL, NULL, 'M', ' ', NULL, 'Y', 'N', NULL, NULL, NULL, 'patcharc', NULL, NULL, NULL, 'DSS-UP', NULL, NULL, NULL, NULL, 'patcharc', '2025-06-16 00:00:00.000', NULL, 'A', 'AP', 'patcharc', '2025-06-13 11:24:57.307', 'patcharc', '2025-06-13 11:24:57.307', NULL, NULL, 'GAMEON', NULL),   -- 10004149 TEST_ESIM_TESTUPLOAD321 -> อยู่ใน view
    (10004150, 10004150, '10205000000000000000000000000000000000PK2025061100083', 'BNO', '3PP', 'Ragnarok Origin Global_2300 Nyan Berry', 2, 'PLM25068779', 'CSH', 'N', 'AWN', 'AWN', '10205', 'Monthly', NULL, 'N', NULL, 'S', ' ', NULL, NULL, NULL, NULL, NULL, 'CPR', ' ', NULL, 1623.360000, 1736.995200, NULL, 'N', NULL, NULL, 'M', ' ', NULL, 'Y', 'N', NULL, NULL, NULL, 'patcharc', NULL, NULL, NULL, 'DSS-UP', NULL, NULL, NULL, NULL, 'patcharc', '2025-06-16 00:00:00.000', NULL, 'A', 'AP', 'patcharc', '2025-06-13 11:24:57.323', 'patcharc', '2025-06-13 11:24:57.323', NULL, NULL, 'GAMEON', NULL),   -- 10004150 TEST_ESIM_TESTUPLOAD309 -> อยู่ใน view
    (10004151, 10004151, '10205000000000000000000000000000000000PK2025061100084', 'BNO', '3PP', 'Ragnarok Origin Global_4800 Nyan Berry', 2, 'PLM25068779', 'CSH', 'N', 'AWN', 'AWN', '10205', 'Monthly', NULL, 'N', NULL, 'S', ' ', NULL, NULL, NULL, NULL, NULL, 'CPR', ' ', NULL, 3313.080000, 3544.995600, NULL, 'N', NULL, NULL, 'M', ' ', NULL, 'Y', 'N', NULL, NULL, NULL, 'patcharc', NULL, NULL, NULL, 'DSS-UP', NULL, NULL, NULL, NULL, 'patcharc', '2025-06-16 00:00:00.000', NULL, 'A', 'AP', 'patcharc', '2025-06-13 11:24:57.337', 'patcharc', '2025-06-13 11:24:57.337', NULL, NULL, 'GAMEON', NULL),   -- 10004151 TEST_ESIM_TESTUPLOAD310 -> อยู่ใน view
    (10004152, 10004152, '10205000000000000000000000000000000000PK2025061100099', 'BNO', '3PP', 'Ragnarok Origin Global_9600 Nyan Berry', 2, 'PLM25068779', 'CSH', 'N', 'AWN', 'AWN', '10205', 'Monthly', NULL, 'N', NULL, 'S', ' ', NULL, NULL, NULL, NULL, NULL, 'CPR', ' ', NULL, 6621.500000, 7085.005000, NULL, 'N', NULL, NULL, 'M', ' ', NULL, 'Y', 'N', NULL, NULL, NULL, 'patcharc', NULL, NULL, NULL, 'DSS-UP', NULL, NULL, NULL, NULL, 'patcharc', '2025-06-16 00:00:00.000', NULL, 'A', 'AP', 'patcharc', '2025-06-13 11:24:57.353', 'patcharc', '2025-06-13 11:24:57.353', NULL, NULL, 'GAMEON', NULL),   -- 10004152 TEST_ESIM_TESTUPLOAD311 -> อยู่ใน view
    (10004153, 10004153, '10205000000000000000000000000000000000PK2025061100089', 'BNO', '3PP', 'Ragnarok Origin Global_24000 Nyan Berry', 2, 'PLM25068779', 'CSH', 'N', 'AWN', 'AWN', '10205', 'Monthly', NULL, 'N', NULL, 'S', ' ', NULL, NULL, NULL, NULL, NULL, 'CPR', ' ', NULL, 16541.120000, 17698.998400, NULL, 'N', NULL, NULL, 'M', ' ', NULL, 'Y', 'N', NULL, NULL, NULL, 'patcharc', NULL, NULL, NULL, 'DSS-UP', NULL, NULL, NULL, NULL, 'patcharc', '2025-06-16 00:00:00.000', NULL, 'A', 'AP', 'patcharc', '2025-06-13 11:24:57.370', 'patcharc', '2025-06-13 11:24:57.370', NULL, NULL, 'GAMEON', NULL)   -- 10004153 TEST_ESIM_TESTUPLOAD312 -> อยู่ใน view
) v([service_id], [service_profile_runno], [service_ref], [service_mkt_type], [network_type], [service_desc], [business_group], [document_no], [share_basis], [check_payment], [invoicing_company_id], [settle_company], [content_partner_id], [settle_period], [service_group], [content_duplicate], [stand_alone], [package_type], [acc_package_type], [cost_center], [profit_center], [gl_code], [gl_name], [wbs], [usage_rate], [charging_unit], [price_rate_type], [price_rate], [full_price], [base_on_price], [discount_price_flag], [discount_price], [mkt_cost_sub], [service_period], [charging_type], [charging_value], [is_cdr_zero_share], [minimum_guarantee], [unit_type], [period], [guarantee_effective_date], [approve_by], [approve_date], [hard_service_status], [hold_service_status], [channel], [service_id_ref], [reject_reason], [reject_reason_code], [reason_code], [checker], [effective_date], [expired_date], [record_status], [wf_status], [created_by], [created_dt], [updated_by], [updated_dt], [remark], [mkt_absorb], [business_group_sub], [ref_ee_id])
WHERE NOT EXISTS (SELECT 1 FROM dss_master.tb_service_profile x WHERE x.[service_profile_runno] = v.[service_profile_runno]);
SET IDENTITY_INSERT dss_master.tb_service_profile OFF;
GO

PRINT '-- seed dss_master.tb_service_bno_key (11 rows)';
INSERT INTO dss_master.tb_service_bno_key
    ([service_profile_runno], [bill_number], [service_bos_online], [service_desc], [record_status], [created_by], [created_dt], [updated_by], [updated_dt], [remark])
SELECT v.* FROM (VALUES
    (10000001, 'ECP_ESIM_Sales_Gable', NULL, NULL, 'A', 'DSS_Migrate', '2024-01-01 00:00:00.000', 'DSS_Migrate', '2024-01-01 00:00:00.000', NULL),   -- 10000001 ECP_ESIM_Sales_Gable
    (10000002, 'ECP_ESIM_Service', NULL, NULL, 'D', 'DSS_Migrate', '2024-01-01 00:00:00.000', 'DSS_Migrate', '2024-01-01 00:00:00.000', NULL),   -- 10000002 ECP_ESIM_Service        -> NEGATIVE: record_status='D'
    (10000048, 'ECP_ESIM_ServiceT', NULL, NULL, 'A', 'budsaf45', '2024-10-31 11:11:25.173', 'budsaf45', '2024-10-31 11:11:25.173', NULL),   -- 10000048 ECP_ESIM_ServiceT
    (10000049, 'ECP_ESIM_SalesT', NULL, NULL, 'A', 'budsaf45', '2024-10-31 11:14:55.030', 'budsaf45', '2024-10-31 11:14:55.030', NULL),   -- 10000049 ECP_ESIM_SalesT         -> ตัวหลักของเคส MAP
    (10000096, 'ECP_ESIM_Step2', NULL, NULL, 'A', 'supakn45', '2024-11-11 16:31:29.827', 'supakn45', '2024-11-11 16:31:29.827', NULL),   -- 10000096 ECP_ESIM_Step2          -> NEGATIVE: orphan ไม่มีแถวใน tb_service_profile
    (10004017, 'ECP_ESIM_SalesSAP', NULL, NULL, 'A', 'kanswa45', '2025-03-12 16:19:34.420', 'kanswa45', '2025-03-12 16:19:34.420', NULL),   -- 10004017 ECP_ESIM_SalesSAP       -> NEGATIVE: profile เป็น USC
    (10004149, 'TEST_ESIM_TESTUPLOAD321', NULL, NULL, 'A', 'pheery45', '2025-04-10 12:13:34.930', 'pheery45', '2025-04-10 12:13:34.930', NULL),   -- 10004149 TEST_ESIM_TESTUPLOAD321
    (10004150, 'TEST_ESIM_TESTUPLOAD309', NULL, NULL, 'A', 'pheery45', '2025-04-10 14:03:48.493', 'pheery45', '2025-04-10 14:03:48.493', NULL),   -- 10004150 TEST_ESIM_TESTUPLOAD309
    (10004151, 'TEST_ESIM_TESTUPLOAD310', NULL, NULL, 'A', 'pheery45', '2025-04-10 14:03:48.597', 'pheery45', '2025-04-10 14:03:48.597', NULL),   -- 10004151 TEST_ESIM_TESTUPLOAD310
    (10004152, 'TEST_ESIM_TESTUPLOAD311', NULL, NULL, 'A', 'pheery45', '2025-04-10 14:10:17.857', 'pheery45', '2025-04-10 14:10:17.857', NULL),   -- 10004152 TEST_ESIM_TESTUPLOAD311
    (10004153, 'TEST_ESIM_TESTUPLOAD312', NULL, NULL, 'A', 'pheery45', '2025-04-10 14:10:17.880', 'pheery45', '2025-04-10 14:10:17.880', NULL)   -- 10004153 TEST_ESIM_TESTUPLOAD312
) v([service_profile_runno], [bill_number], [service_bos_online], [service_desc], [record_status], [created_by], [created_dt], [updated_by], [updated_dt], [remark])
WHERE NOT EXISTS (SELECT 1 FROM dss_master.tb_service_bno_key x WHERE x.[service_profile_runno] = v.[service_profile_runno]);
GO



/* --- 5. VERIFY ----------------------------------------------------------- */
PRINT '';
PRINT '=== 5.1 cdr_type ที่ task 040000 ต้อง join ให้ติด (ต้องได้ 1 แถว) ===';
SELECT cdr_type_runno, cdr_type, source_path, data_table, record_status
FROM   dss_master.tb_master_cdr_type
WHERE  cdr_type = '1' AND record_status = 'A';
GO

PRINT '=== 5.2 mapping ESIM ที่ view ปล่อยผ่าน (ต้องได้ 8 แถว) ===';
SELECT b_no, invoicing_company_id, content_partner_id, service_id, network_type,
       share_basis, price_rate_type, record_status,
       CONVERT(varchar(10), effective_date, 120) AS effective_date,
       CONVERT(varchar(10), expired_date  , 120) AS expired_date
FROM   dss_master.vw_service_mapping_bno_key
WHERE  b_no LIKE '%[_]ESIM[_]%'
ORDER  BY b_no;
GO

PRINT '=== 5.3 จำลองเงื่อนไข join ของ 040000 ที่ first_installed = 2026-08-27 ===';
PRINT '     ต้องเห็น ECP_ESIM_SalesT  แต่ต้องไม่เห็น ECP_ESIM_Sales_Gable (หมดอายุแล้ว)';
SELECT b_no, invoicing_company_id, content_partner_id, service_id, network_type, share_basis
FROM   dss_master.vw_service_mapping_bno_key
WHERE  record_status = 'A'
  AND  b_no LIKE '%[_]ESIM[_]%'
  AND  content_partner_id   IS NOT NULL
  AND  service_id           IS NOT NULL
  AND  network_type         IS NOT NULL
  AND  invoicing_company_id IS NOT NULL
  AND  share_basis          IS NOT NULL
  AND  effective_date <= '2026-08-27'
  AND  (expired_date IS NULL OR expired_date >= '2026-08-27')
ORDER  BY b_no;
GO

PRINT '=== 5.4 ยืนยันว่า ECP_ESIM_Step ไม่มีจริง (เคส UNMAP U01-U03) - ต้องได้ 0 ===';
SELECT COUNT(*) AS must_be_zero
FROM   dss_master.vw_service_mapping_bno_key
WHERE  b_no = 'ECP_ESIM_Step';
GO

PRINT '=== 5.5 negative control 3 แถว - ต้องมีอยู่ในตารางฐาน แต่ต้องไม่โผล่ใน view ===';
SELECT k.service_profile_runno,
       k.bill_number,
       k.record_status        AS bnokey_status,
       p.service_mkt_type,
       p.record_status        AS profile_status,
       p.wf_status,
       CASE WHEN v.b_no IS NULL THEN 'ตกจาก view (ถูกต้อง)' ELSE 'โผล่ใน view (ผิด!)' END AS result
FROM   dss_master.tb_service_bno_key k
LEFT   JOIN dss_master.tb_service_profile p ON p.service_profile_runno = k.service_profile_runno
LEFT   JOIN dss_master.vw_service_mapping_bno_key v ON v.b_no = k.bill_number
WHERE  k.service_profile_runno IN (10000002, 10000096, 10004017);
GO

PRINT '=== 5.6 ตรวจ b_no ซ้ำ (ต้องได้ 0 แถว มิฉะนั้น 040000 จะเกิด row multiplication) ===';
SELECT b_no, invoicing_company_id, COUNT(*) AS dup_cnt
FROM   dss_master.vw_service_mapping_bno_key
WHERE  b_no LIKE '%[_]ESIM[_]%'
GROUP  BY b_no, invoicing_company_id
HAVING COUNT(*) > 1;
GO


/* --- 6. ROLLBACK --------------------------------------------------------- */
/* ลบเฉพาะแถวที่สคริปต์นี้ใส่เข้าไป - เปิดคอมเมนต์เมื่อต้องการล้าง

DELETE FROM dss_master.tb_service_bno_key
WHERE  service_profile_runno IN (10000001,10000002,10000048,10000049,10000096,10004017,10004149,10004150,10004151,10004152,10004153);

DELETE FROM dss_master.tb_service_profile
WHERE  service_profile_runno IN (10000001,10000002,10000048,10000049,10004017,10004149,10004150,10004151,10004152,10004153);

DELETE FROM dss_master.tb_master_cdr_type
WHERE  cdr_type = '1' AND data_table = 'ss_esim';

-- ถ้าต้องการรื้อทั้งหมด (เฉพาะ environment ที่สร้างใหม่เท่านั้น!)
-- DROP VIEW  dss_master.vw_service_mapping_bno_key;
-- DROP TABLE dss_master.tb_service_bno_key;
-- DROP TABLE dss_master.tb_service_profile;
-- DROP TABLE dss_master.tb_master_cdr_type;

*/

PRINT '';
PRINT '=== seed เสร็จสิ้น ===';
GO
