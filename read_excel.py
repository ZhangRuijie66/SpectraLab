import openpyxl

wb = openpyxl.load_workbook('说明.xlsx')
for sheet_name in wb.sheetnames:
    ws = wb[sheet_name]
    print(f'=== Sheet: {sheet_name} ===')
    for row in ws.iter_rows(values_only=True):
        print(row)
