import csv
import collections
import os

def merge_overlapping_csv_rows(csv_data_list, compare_fields):
    """Merge overlapping CSV files.

    Rows are compared based on the list 'compare_fields' of field names.
    The number of duplicate copies of a row kept in the result is equal
    to the maximum number of duplicates in any single file.

    :param csv_data_list: list of rows, each row being represented by a
        dict
    :param compare_fields: list of field names by which duplicates are
        detected.

    :return: Returns the merged list of rows.
    """
    def convert_row(row):
        return tuple(row[field] for field in compare_fields)
    merged_counter = collections.Counter()
    merged_rows = []
    for csv_data in csv_data_list:
        cur_counter = collections.Counter()
        for row in csv_data:
            converted_row = convert_row(row)
            cur_counter[converted_row] += 1
            if cur_counter[converted_row] > merged_counter[converted_row]:
                merged_rows.append(row)
                merged_counter[converted_row] += 1
    return merged_rows

def write_csv(field_names, data, filename):
    tmp_filename = filename + '.tmp'
    with open(tmp_filename, 'w', newline='') as f:
        csv_writer = csv.DictWriter(f, field_names, lineterminator='\n',
                                    quoting=csv.QUOTE_ALL)
        csv_writer.writeheader()
        csv_writer.writerows(data)
    os.rename(tmp_filename, filename)

def merge_into_file(filename,
                    field_names, data,
                    sort_by=None,
                    compare_fields=None):
    if compare_fields is None:
        compare_fields = field_names

    if os.path.exists(filename):
        with open(filename, 'r', newline='') as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == field_names, (reader.fieldnames, field_names)
            existing_rows = list(reader)
        data = merge_overlapping_csv_rows([existing_rows, data],
                                              compare_fields=compare_fields)
    if sort_by is not None:
        data.sort(key=sort_by)
    write_csv(field_names=field_names, data=data, filename=filename)
