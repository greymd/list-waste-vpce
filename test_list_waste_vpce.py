import boto3
from list_waste_vpce import has_private_eni, SubnetType
region = 'ap-northeast-1'

def test_has_private_eni_true():
    ec2_client = boto3.client('ec2', region_name=region)
    # Replace with your subnet having private ENI
    result = has_private_eni(ec2_client, 'subnet-xxxxxxxxxxxxxxxxx')
    assert result == SubnetType.PRIVATE

def test_has_private_eni_false():
    ec2_client = boto3.client('ec2', region_name=region)
    # Replace with your subnet having public ENI only
    result = has_private_eni(ec2_client, 'subnet-xxxxxxxxxxxxxxxxx')
    assert result == SubnetType.PUBLIC
