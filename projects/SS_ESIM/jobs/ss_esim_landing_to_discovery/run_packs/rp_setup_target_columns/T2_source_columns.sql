-- Source table columns (landing data contract, preflight P3). Single SELECT, read-only: Ctrl+Enter in DBeaver, export CSV with header -> input/oracle_ddl/source_columns.csv
-- Tables the job only reads: EXT_DSS_CHECKPOINT_TB_TRANSACTION_SS_ESIM_VALID, EXT_DSS_TB_MASTER_CDR_TYPE, EXT_DSS_VW_SERVICE_MAPPING_BNO_KEY, TB_LANDING_SS_ESIM
SELECT owner, table_name, column_id, column_name, data_type, data_length,
       data_precision, data_scale, nullable, data_default
FROM   all_tab_columns
WHERE  table_name IN ('EXT_DSS_CHECKPOINT_TB_TRANSACTION_SS_ESIM_VALID', 'EXT_DSS_TB_MASTER_CDR_TYPE', 'EXT_DSS_VW_SERVICE_MAPPING_BNO_KEY', 'TB_LANDING_SS_ESIM')
ORDER  BY table_name, owner, column_id
