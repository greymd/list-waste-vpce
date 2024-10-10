import boto3
import sys

def main(region):
    # List all NAT Gateways and check if they are in available state
    ec2 = boto3.client('ec2', region_name=region)
    response = ec2.describe_nat_gateways()
    for nat_gateway in response['NatGateways']:
        if nat_gateway['State'] != 'available':
            print(f"WARNING: NAT Gateway {nat_gateway['NatGatewayId']} is in state {nat_gateway['State']}")
    print(f"INFO: Total NAT Gateways: {len(response['NatGateways'])}")
    return

if __name__ == '__main__':
    region = 'ap-northeast-1'
    if len(sys.argv) > 1:
        if sys.argv[1] == '--help':
            print(f"Usage: {sys.argv[0]} --region <region>")
            sys.exit(0)
        if sys.argv[1] == '--region':
            region = sys.argv[2]
    main(region)
