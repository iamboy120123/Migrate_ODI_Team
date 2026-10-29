#!/usr/bin/env node
/*
 * Test-data generator for CDR ss_esim  (Blendata: landing -> discovery)
 *
 *   layout : body_tag|partner|owner|iccid|first_installed|profile_type|eid|sim_type
 *   ingest : service_stream_data          -> WHERE value[0]='02'
 *   batch  : 040000_overwrite_ss_esim_raw_temp -> MAP / UNMAP / DUP / MAN / TYP
 *
 * ค่าทั้งหมดด้านล่างยืนยันจาก dev DB จริงแล้ว เมื่อ 2026-08-27
 * (connection ดูที่ env-dev.md ที่ root ของโปรเจกต์ - ห้าม hardcode ลงไฟล์นี้)
 *
 *   dss_master.tb_master_cdr_type
 *     cdr_type='1' -> data_table='ss_esim', source_path='file:/sources_dev/Phoenix/eSIM',
 *     record_status='A'  (มีแถวเดียว -> inner join ใน 040000 ไม่ทำให้แถวคูณ)
 *
 *   dss_master.vw_service_mapping_bno_key  (b_no LIKE '%_ESIM_%', record_status='A' = 8 แถว)
 *     b_no                     inv_co  cp_id  service_id  net  share  effective    expired
 *     ECP_ESIM_Sales_Gable     AWN     10100  10000001    3PP  CSH    2024-01-01   2025-12-31
 *     ECP_ESIM_SalesT          AWN     10128  10000049    3PP  CSH    2025-01-16   (null)
 *     ECP_ESIM_ServiceT        AWN     10128  10000048    3PP  CSH    2025-01-16   (null)
 *     TEST_ESIM_TESTUPLOAD309  AWN     10205  10004150    3PP  CSH    2025-06-16   (null)
 *     TEST_ESIM_TESTUPLOAD310..312, 321  (เหมือนกัน)
 *     -> invoicing_company_id มีแค่ AWN (829 แถว) กับ 3BB (6 แถว) ทั้งระบบ
 *     -> price_rate_type ว่างทุกแถว แต่ไม่อยู่ใน mapping_error check จึงไม่ทำให้เป็น UNMAP
 *     -> ไม่มี b_no ซ้ำ -> ไม่มีความเสี่ยง row multiplication
 *
 *   dss_transaction.tb_transaction_ss_esim_valid (ข้อมูลจริง 16 แถว) ใช้อ้างอิงรูปทรงข้อมูล
 *     partner=ECP  owner=AWN  sim_type=Step/Step2  profile_type=Production
 *     iccid 11 หลัก (24102517043)   eid 9 หลัก (987654321)
 *     cdr_id 26 หลัก (20241108181522 + 001 + 000000001)
 *     cdr_filename = viewfs://.../imports/ss_esim/PGZ_ESIM_INVENTORY1_20241108_140001_1.txt
 *     *** b_no 'ECP_ESIM_Step'/'ECP_ESIM_Step2' ไม่มีใน master แล้ว -> ใช้ทำเคส UNMAP ได้จริง ***
 *
 * usage: node gen_esim_testdata.js [outDir]
 */
const fs = require('fs');
const path = require('path');

// ---------------------------------------------------------------------------
// CONFIG
// ---------------------------------------------------------------------------
const CFG = {
  PARTNER:          'ECP',          // partner จริงในข้อมูล production
  OWNER:            'AWN',          // = invoicing_company_id ของ mapping ESIM ทุกแถว
  PROFILE:          'Production',   // profile_type จริง

  SIM_MAPPED:       'SalesT',       // ECP_ESIM_SalesT      : effective 2025-01-16, ไม่มีวันหมด -> MAP
  SIM_EXPIRED:      'Sales_Gable',  // ECP_ESIM_Sales_Gable : หมดอายุ 2025-12-31        -> UNMAP
  SIM_GONE:         'Step',         // ECP_ESIM_Step        : เคยใช้จริง แต่ถูกถอดออกจาก master -> UNMAP
  OWNER_WRONG:      '3BB',          // มีจริงในระบบ แต่ไม่ใช่เจ้าของ mapping ESIM         -> UNMAP

  BASE_DAY:         '20260827',     // วันที่เทส (อยู่หลัง effective ของ SalesT และหลัง expired ของ Sales_Gable)
  DAY_BEFORE_EFF:   '20240101',     // ก่อน effective 2025-01-16 ของ SalesT              -> UNMAP

  // ชื่อไฟล์ยึดตามของจริง : PGZ_ESIM_INVENTORY1_<yyyyMMdd>_<HHmmss>_<running>.txt
  //   ชั้น 1  glob  '.../imports/ss_esim/PGZ_ESIM_INVENTORY*.txt'  (case-sensitive)
  //   ชั้น 2  regex '(.+)([_])(\d{8}[_]\d{6})([_])(.+[.].+)' group 3 -> file_date
  //           ต้องมี _ ทั้งหน้าและหลังบล็อกวันเวลา และต้องปิดท้ายด้วย <running>.<ext>
  // *** เทสรอบใหม่ต้องเปลี่ยน STAMP ทุกครั้ง ไม่งั้นชนกับไฟล์เดิมใน archive ***
  PREFIX:           'PGZ_ESIM_INVENTORY1',
  STAMP_MAIN:       '20260827_100000',   // running 1
  STAMP_DUP:        '20260827_101000',   // running 2
  STAMP_GOTCHA:     '20260827_102000',   // running 3
  STAMP_NOSEQ:      '20260827_103000',   // ไม่มี running -> file_date NULL (negative)
  STAMP_BADGLOB:    '20260827_104000',   // running 5 แต่ prefix ผิด        (negative)
  STAMP_RESEND:     '20260827_110000',   // running 4  (วางรอบถัดไป)
};

const OUT = process.argv[2] || __dirname;

// ---------------------------------------------------------------------------
// helper : รูปทรงข้อมูลอ้างอิงของจริง  iccid 11 หลัก / eid 9 หลัก
const iccid = (grp, i) => '2608' + grp + String(i).padStart(6, '0');
const eid   = (grp, i) => '9'    + grp + String(i).padStart(7, '0');
const ts    = (hhmmss, day) => (day || CFG.BASE_DAY) + hhmmss;

const rows = [];
const add  = (o) => rows.push(o);

/** ประกอบ 1 บรรทัด body */
const body = (f) => [
  '02', f.partner, f.owner, f.iccid, f.first_installed, f.profile_type, f.eid, f.sim_type,
].join('|');

const P = CFG.PARTNER, O = CFG.OWNER, S = CFG.SIM_MAPPED;

// ===========================================================================
// FILE 1 - MAIN : not-streamed x10 + MAP x10 + UNMAP x10 + MAN x10 + TYP x10
// ===========================================================================
const F1 = CFG.PREFIX + '_' + CFG.STAMP_MAIN + '_1.txt';

// -- กลุ่ม X : ต้องถูก DROP ที่ stream (WHERE value[0]='02') -----------------
const notStreamed = [
  ['X01', '01|' + CFG.BASE_DAY + '|100000|ESIM_INVENTORY|' + P, 'header record (body_tag=01)'],
  ['X02', '99|000050|' + ts('100000'),                          'trailer record (body_tag=99)'],
  ['X03', '03|' + P + '|' + O + '|26089000001|' + ts('100000') + '|' + CFG.PROFILE + '|' + eid('9', 1) + '|' + S, 'tag แปลกปลอม 03'],
  ['X04', '|'   + P + '|' + O + '|26089000002|' + ts('100000') + '|' + CFG.PROFILE + '|' + eid('9', 2) + '|' + S, 'body_tag ว่าง'],
  ['X05', '002|' + P + '|' + O + '|26089000003|' + ts('100000') + '|' + CFG.PROFILE + '|' + eid('9', 3) + '|' + S, "'002' != '02'"],
  ['X06', ' 02|' + P + '|' + O + '|26089000004|' + ts('100000') + '|' + CFG.PROFILE + '|' + eid('9', 4) + '|' + S, 'มี space นำหน้า'],
  ['X07', '02 |' + P + '|' + O + '|26089000005|' + ts('100000') + '|' + CFG.PROFILE + '|' + eid('9', 5) + '|' + S, 'มี space ต่อท้าย'],
  ['X08', '2|'   + P + '|' + O + '|26089000006|' + ts('100000') + '|' + CFG.PROFILE + '|' + eid('9', 6) + '|' + S, "'2' ไม่มี leading zero"],
  ['X09', 'HEADER RECORD ESIM INVENTORY ' + CFG.BASE_DAY,       'ไม่มี pipe เลย'],
  ['X10', '',                                                   'บรรทัดว่าง'],
];

// -- กลุ่ม M : MAP x10  (b_no = ECP_ESIM_SalesT, owner AWN, 2026-08-27) -----
const mapIccids = [];
for (let i = 1; i <= 10; i++) {
  const ic = iccid('1', i);
  mapIccids.push(ic);
  add({
    file: F1, caseId: 'M' + String(i).padStart(2, '0'),
    raw: body({
      partner: P, owner: O, iccid: ic,
      first_installed: ts(String(90000 + i * 100).padStart(6, '0')),
      profile_type: CFG.PROFILE, eid: eid('1', i), sim_type: S,
    }),
    streamed: 'Y', status: 'MAP', table: 'tb_transaction_ss_esim_valid',
    note: 'b_no=' + P + '_ESIM_' + S + ' + owner=' + O + ' + อยู่ในช่วง effective -> cp_id/service_id/network_type/share_basis ครบ',
  });
}

// -- กลุ่ม U : UNMAP x10 (4 sub-case จาก master จริง) -----------------------
const unmapCases = [];
[1, 2, 3].forEach((i) => unmapCases.push({
  i, partner: P, owner: O, sim: CFG.SIM_GONE, fi: ts('100000'),
  note: "b_no '" + P + '_ESIM_' + CFG.SIM_GONE + "' เคยใช้จริงแต่ถูกถอดออกจาก master แล้ว -> ไม่เจอ mapping",
}));
[4, 5, 6].forEach((i) => unmapCases.push({
  i, partner: P, owner: CFG.OWNER_WRONG, sim: S, fi: ts('100000'),
  note: "owner '" + CFG.OWNER_WRONG + "' มีจริงในระบบ แต่ mapping ESIM เป็นของ '" + O + "' -> join ไม่ติด",
}));
[7, 8].forEach((i) => unmapCases.push({
  i, partner: P, owner: O, sim: S, fi: ts('100000', CFG.DAY_BEFORE_EFF),
  note: 'first_installed ' + CFG.DAY_BEFORE_EFF + ' < effective_date 2025-01-16 ของ ' + P + '_ESIM_' + S,
}));
[9, 10].forEach((i) => unmapCases.push({
  i, partner: P, owner: O, sim: CFG.SIM_EXPIRED, fi: ts('100000'),
  note: 'first_installed ' + CFG.BASE_DAY + ' > expired_date 2025-12-31 ของ ' + P + '_ESIM_' + CFG.SIM_EXPIRED,
}));
unmapCases.forEach((c) => add({
  file: F1, caseId: 'U' + String(c.i).padStart(2, '0'),
  raw: body({
    partner: c.partner, owner: c.owner, iccid: iccid('2', c.i), first_installed: c.fi,
    profile_type: CFG.PROFILE, eid: eid('2', c.i), sim_type: c.sim,
  }),
  streamed: 'Y', status: 'UNMAP', table: 'tb_transaction_ss_esim_temp (delta)', note: c.note,
}));

// -- กลุ่ม N : MAN x10 (mandatory ขาด) --------------------------------------
const baseRow = (i) => ({
  partner: P, owner: O, iccid: iccid('3', i), first_installed: ts('100000'),
  profile_type: CFG.PROFILE, eid: eid('3', i), sim_type: S,
});
const manCases = [
  [1, { partner: '' },                               'partner|'],
  [2, { owner: '' },                                 'owner|'],
  [3, { iccid: '' },                                 'iccid|'],
  [4, { first_installed: '' },                       'first_installed|'],
  [5, { profile_type: '' },                          'profile_type|'],
  [6, { sim_type: '' },                              'sim_type|'],
  [7, { partner: '', owner: '' },                    'partner|owner|'],
  [8, { iccid: '', profile_type: '', sim_type: '' }, 'iccid|profile_type|sim_type|'],
  [9, { partner: '', owner: '', iccid: '', first_installed: '', profile_type: '', sim_type: '' },
      'partner|owner|iccid|first_installed|profile_type|sim_type|'],
];
manCases.forEach((c) => add({
  file: F1, caseId: 'N' + String(c[0]).padStart(2, '0'),
  raw: body(Object.assign({}, baseRow(c[0]), c[1])),
  streamed: 'Y', status: 'MAN', table: 'tb_transaction_ss_esim_reject',
  note: "filter_error = '" + c[2] + "'",
}));
// N10 : แถวสั้น 5 คอลัมน์ -> profile_type / eid / sim_type = null
add({
  file: F1, caseId: 'N10',
  raw: ['02', P, O, iccid('3', 10), ts('100000')].join('|'),
  streamed: 'Y', status: 'MAN', table: 'tb_transaction_ss_esim_reject',
  note: "แถวสั้น 5 คอลัมน์ -> number_of_cols=5, filter_error='profile_type|sim_type|'",
});

// -- กลุ่ม T : TYP x10 (first_installed แปลง timestamp ไม่ผ่าน) -------------
const typCases = [
  [1,  '20261327100000',   'เดือน 13'],
  [2,  '20260832100000',   'วันที่ 32'],
  [3,  '20260827250000',   'ชั่วโมง 25'],
  [4,  '20260827106000',   'นาที 60'],
  [5,  '20260827100099',   'วินาที 99'],
  [6,  '20260229100000',   '29 ก.พ. ปี 2026 ไม่ใช่ปีอธิกสุรทิน'],
  [7,  '2026-08-27T10:00', "มี separator -> left(...,14) = '2026-08-27T10:'"],
  [8,  '20260827',         'สั้นเกิน (8 หลัก)'],
  [9,  'ABCDEFGHIJKLMN',   'ไม่ใช่ตัวเลข'],
  [10, '00000000000000',   'ศูนย์ล้วน (เดือน/วัน = 00)'],
];
typCases.forEach((c) => add({
  file: F1, caseId: 'T' + String(c[0]).padStart(2, '0'),
  raw: body({
    partner: P, owner: O, iccid: iccid('4', c[0]), first_installed: c[1],
    profile_type: CFG.PROFILE, eid: eid('4', c[0]), sim_type: S,
  }),
  streamed: 'Y', status: 'TYP', table: 'tb_transaction_ss_esim_reject',
  note: 'type_error: ' + c[2],
}));

// ===========================================================================
// FILE 2 - DUP x10 : ICCID ซ้ำกับ M01..M10 แต่ file_date ใหม่กว่า
//   rn = ROW_NUMBER() OVER (PARTITION BY chk_duplicate, status ORDER BY file_date)
//   -> ตัวใน FILE 1 (file_date เก่ากว่า) = rn 1 = MAP
//   -> ตัวใน FILE 2                      = rn 2 = DUP
//   *** ต้องวางพร้อม FILE 1 ให้เข้า workflow รอบเดียวกัน ***
// ===========================================================================
const F2 = CFG.PREFIX + '_' + CFG.STAMP_DUP + '_2.txt';
mapIccids.forEach((ic, idx) => {
  const i = idx + 1;
  add({
    file: F2, caseId: 'D' + String(i).padStart(2, '0'),
    raw: body({
      partner: P, owner: O, iccid: ic,
      first_installed: ts(String(90000 + i * 100).padStart(6, '0')),
      profile_type: CFG.PROFILE, eid: eid('1', i), sim_type: S,
    }),
    streamed: 'Y', status: 'DUP', table: 'tb_transaction_ss_esim_reject',
    note: 'in-batch dup ของ M' + String(i).padStart(2, '0') + ' (file_date ใหม่กว่า -> rn=2)',
  });
});

// ===========================================================================
// FILE 3 - RESEND : cross-run DUP  *** วางใน workflow รอบถัดไป ***
//   join dup = (valid UNION temp) -> status='DUP' ตั้งแต่ layer 3, rn = -99
// ===========================================================================
const F3 = CFG.PREFIX + '_' + CFG.STAMP_RESEND + '_4.txt';
mapIccids.forEach((ic, idx) => {
  const i = idx + 1;
  add({
    file: F3, caseId: 'R' + String(i).padStart(2, '0'),
    raw: body({
      partner: P, owner: O, iccid: ic,
      first_installed: ts(String(90000 + i * 100).padStart(6, '0')),
      profile_type: CFG.PROFILE, eid: eid('1', i), sim_type: S,
    }),
    streamed: 'Y', status: 'DUP', table: 'tb_transaction_ss_esim_reject',
    note: 'cross-run dup: ชน chk_duplicate ที่ลง tb_transaction_ss_esim_valid ไปแล้วรอบก่อน',
  });
});

// ===========================================================================
// FILE 4 - GOTCHA : เคสที่ "ดูเหมือนจะพัง แต่ผ่าน" - ไว้พิสูจน์ช่องโหว่ validation
// ===========================================================================
const F4 = CFG.PREFIX + '_' + CFG.STAMP_GOTCHA + '_3.txt';
add({
  file: F4, caseId: 'G01',
  raw: body({ partner: P, owner: O, iccid: iccid('5', 1), first_installed: ts('100000'),
              profile_type: CFG.PROFILE, eid: '', sim_type: S }),
  streamed: 'Y', status: 'MAP', table: 'tb_transaction_ss_esim_valid',
  note: 'eid ว่าง -> ยัง MAP เพราะ eid ไม่อยู่ใน mandatory list',
});
add({
  file: F4, caseId: 'G02',
  raw: body({ partner: P, owner: O, iccid: iccid('5', 2), first_installed: ts('100000'),
              profile_type: CFG.PROFILE, eid: eid('5', 2), sim_type: S }) + '|EXTRA1|EXTRA2',
  streamed: 'Y', status: 'MAP', table: 'tb_transaction_ss_esim_valid',
  note: 'เกิน 8 คอลัมน์ -> number_of_cols=10 แต่ยัง MAP (คอลัมน์เกินถูกทิ้งเงียบ)',
});
add({
  file: F4, caseId: 'G03',
  raw: body({ partner: ' ', owner: O, iccid: iccid('5', 3), first_installed: ts('100000'),
              profile_type: CFG.PROFILE, eid: eid('5', 3), sim_type: S }),
  streamed: 'Y', status: 'UNMAP', table: 'tb_transaction_ss_esim_temp (delta)',
  note: "partner เป็น space -> nullif(x,'') ไม่จับ -> ไม่เป็น MAN แต่ b_no = ' _ESIM_" + S + "' -> UNMAP",
});
add({
  file: F4, caseId: 'G04',
  raw: body({ partner: P, owner: O, iccid: iccid('5', 4), first_installed: ts('100000') + '123',
              profile_type: CFG.PROFILE, eid: eid('5', 4), sim_type: S }),
  streamed: 'Y', status: 'MAP', table: 'tb_transaction_ss_esim_valid',
  note: 'first_installed 17 หลัก -> left(...,14) ตัดส่วนเกินทิ้งเงียบ ๆ -> MAP',
});
add({
  file: F4, caseId: 'G05',
  raw: body({ partner: P, owner: O, iccid: ' ' + mapIccids[0] + ' ', first_installed: ts('100000'),
              profile_type: CFG.PROFILE, eid: eid('5', 5), sim_type: S }),
  streamed: 'Y', status: 'MAP', table: 'tb_transaction_ss_esim_valid',
  note: 'ICCID เดียวกับ M01 แต่มี space ครอบ -> chk_duplicate ไม่ตรง -> dedup หลุด กลายเป็น MAP ซ้ำ!',
});
add({
  file: F4, caseId: 'G06',
  raw: body({ partner: P.toLowerCase(), owner: O, iccid: iccid('5', 6), first_installed: ts('100000'),
              profile_type: CFG.PROFILE, eid: eid('5', 6), sim_type: S }),
  streamed: 'Y', status: 'UNMAP', table: 'tb_transaction_ss_esim_temp (delta)',
  note: "partner ตัวพิมพ์เล็ก 'ecp' -> b_no ไม่ตรงกับ master (Spark join case-sensitive) -> UNMAP",
});

// ===========================================================================
// FILE 5 - ขาด _<running> ต่อท้าย : เข้า stream ได้ แต่ file_date = NULL
// ===========================================================================
const F5 = CFG.PREFIX + '_' + CFG.STAMP_NOSEQ + '.txt';
for (let i = 1; i <= 3; i++) {
  add({
    file: F5, caseId: 'FN' + String(i).padStart(2, '0'),
    raw: body({ partner: P, owner: O, iccid: iccid('6', i), first_installed: ts('100000'),
                profile_type: CFG.PROFILE, eid: eid('6', i), sim_type: S }),
    streamed: 'Y', status: 'MAP (file_date=NULL)', table: 'tb_transaction_ss_esim_valid',
    note: 'ขาด _<running> ต่อท้าย -> regex ไม่แมตช์ -> file_date NULL (ASC NULLS FIRST จะชนะ dedup)',
  });
}

// ===========================================================================
// FILE 6 - prefix ผิด ไม่แมตช์ glob PGZ_ESIM_INVENTORY*.txt : ไม่เข้าระบบเลย
// ===========================================================================
const F6 = 'ESIM_INVENTORY1_' + CFG.STAMP_BADGLOB + '_5.txt';
for (let i = 1; i <= 3; i++) {
  add({
    file: F6, caseId: 'FG' + String(i).padStart(2, '0'),
    raw: body({ partner: P, owner: O, iccid: iccid('7', i), first_installed: ts('100000'),
                profile_type: CFG.PROFILE, eid: eid('7', i), sim_type: S }),
    streamed: 'N', status: '-', table: '-',
    note: 'ไม่ขึ้นต้น PGZ_ESIM_INVENTORY -> stream ไม่หยิบ และ cleanSource ก็ไม่ย้าย ต้องลบเอง',
  });
}

// ===========================================================================
// SELF-CHECK : ตรวจชื่อไฟล์ทุกไฟล์กับ glob + regex ก่อนเขียนจริง
// ===========================================================================
const GLOB = /^PGZ_ESIM_INVENTORY.*\.txt$/;
const RE   = /(.+)([_])(\d{8}[_]\d{6})([_])(.+[.].+)/;
const fileDateOf = (n) => { const m = RE.exec(n); return m ? m[3].replace(/_/g, '') : null; };

// ===========================================================================
// WRITE
// ===========================================================================
const files = {};
const f1Lines = [];
f1Lines.push(notStreamed[0][1]);                                    // X01 header
rows.filter((r) => r.file === F1).forEach((r) => f1Lines.push(r.raw));
notStreamed.slice(2, 9).forEach((c) => f1Lines.push(c[1]));         // X03..X09
f1Lines.push('');                                                   // X10 blank
// X02 trailer : นับจำนวน body record (02) จริงในไฟล์ ให้ไฟล์ consistent ในตัวเอง
const f1BodyCount = rows.filter((r) => r.file === F1).length;
notStreamed[1][1] = '99|' + String(f1BodyCount).padStart(6, '0') + '|' + ts('100000');
f1Lines.push(notStreamed[1][1]);
files[F1] = f1Lines;
[F2, F3, F4, F5, F6].forEach((f) => {
  files[f] = rows.filter((r) => r.file === f).map((r) => r.raw);
});

console.log('FILENAME'.padEnd(45) + 'LINES  STREAM  file_date');
console.log('-'.repeat(45) + '-----  ------  --------------');
Object.keys(files).forEach((name) => {
  fs.writeFileSync(path.join(OUT, name), files[name].join('\n') + '\n', { encoding: 'utf8' });
  const fd = fileDateOf(name);
  console.log(name.padEnd(45) + String(files[name].length).padStart(5) + '  ' +
              (GLOB.test(name) ? 'YES   ' : 'NO    ') + '  ' + (fd === null ? 'NULL' : fd));
});

// expected results
const esc = (s) => '"' + String(s).replace(/"/g, '""') + '"';
const csv = [['file', 'case_id', 'expected_streamed', 'expected_status', 'target_table', 'raw_line', 'note'].join(',')];
notStreamed.forEach((c) => csv.push([esc(F1), esc(c[0]), esc('N'), esc('-'), esc('-'), esc(c[1]), esc(c[2])].join(',')));
rows.forEach((r) => csv.push([esc(r.file), esc(r.caseId), esc(r.streamed), esc(r.status), esc(r.table), esc(r.raw), esc(r.note)].join(',')));
fs.writeFileSync(path.join(OUT, 'expected_results.csv'), csv.join('\n') + '\n', { encoding: 'utf8' });
console.log('\nexpected_results.csv : ' + (csv.length - 1) + ' cases');

const tally = { 'NOT-STREAMED (บรรทัด)': notStreamed.length };
rows.forEach((r) => {
  const k = r.streamed === 'N' ? 'NOT-STREAMED (ทั้งไฟล์)' : r.status;
  tally[k] = (tally[k] || 0) + 1;
});
console.log('tally                :', JSON.stringify(tally, null, 2));
