from src.node_dsl.node_typing import IO
from src.nodes.connection.get_exist_db_connection import GetExistDBConnection
from src.nodes.connection.get_exist_ftp_connection import GetExistFTPConnection
from src.nodes.connection.get_exist_smb_connection import GetExistSMBConnection
from src.nodes.connection.get_exist_s3_connection import GetExistS3Connection
from src.nodes.extract.load_csv import LoadCSV
from src.nodes.extract.read_query_from_db_v3 import ReadQueryFromDBV3


def test_connection_output_ports_keep_family_specific_io_types():
    assert GetExistDBConnection.output_fields()["connection"].resolved_type == IO.DB_CONNECTION
    assert GetExistS3Connection.output_fields()["connection"].resolved_type == IO.S3_CONNECTION
    assert GetExistFTPConnection.output_fields()["connection"].resolved_type == IO.FTP_CONNECTION
    assert GetExistSMBConnection.output_fields()["connection"].resolved_type == IO.SMB_CONNECTION


def test_connection_input_ports_accept_expected_io_types():
    assert LoadCSV.input_fields()["connection"].resolved_type == IO.FILE_CONNECTION
    assert ReadQueryFromDBV3.input_fields()["connection"].resolved_type == IO.DB_CONNECTION
