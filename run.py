import boto3
import sys

DEBUG = False
def debug(msg):
    if DEBUG:
        print(f"[debug] {msg}", flush=True, file=sys.stderr)

def result(msg):
    print(f"\033[91m{msg}\033[0m", flush=True, file=sys.stdout)

def is_public_subnet(ec2_client, subnet_id):
    response = ec2_client.describe_route_tables(
        Filters=[
            {'Name': 'association.subnet-id', 'Values': [subnet_id]}
        ]
    )
    for route_table in response['RouteTables']:
        for route in route_table['Routes']:
            if route.get('DestinationCidrBlock') == '0.0.0.0/0':
                if 'GatewayId' in route and route['GatewayId'].startswith('igw-'):
                    debug(f"Subnet ID: {subnet_id} = PUBLIC")
                    return True
                if 'NatGatewayId' in route:
                    debug(f"Subnet ID: {subnet_id} = PUBLIC")
                    return True
    debug(f"Subnet ID: {subnet_id} = PRIVATE")
    return False

def main(region):
    ec2_client = boto3.client('ec2', region_name=region)
    response = ec2_client.describe_vpc_endpoints(
        Filters=[
            {'Name': 'vpc-endpoint-type', 'Values': ['Interface']}
        ]
    )
    aws_api_endpoints = []
    for ep in response['VpcEndpoints']:
        if 'com.amazonaws.' in ep['ServiceName'] and (not 'vpce-svc' in ep['ServiceName']):
            aws_api_endpoints.append(ep)
    vpc_az_is_pub_memo = {}
    for endpoint in aws_api_endpoints:
        vpc_id = endpoint['VpcId']
        eni_azs = set()
        for eni in endpoint['NetworkInterfaceIds']:
            eni_response = ec2_client.describe_network_interfaces(
                NetworkInterfaceIds=[eni]
            )
            eni_azs.add(eni_response['NetworkInterfaces'][0]['AvailabilityZone'])

        for az in eni_azs:
            if f'{vpc_id}-{az}' in vpc_az_is_pub_memo:
                debug(f"VPC Endpoint ID: {endpoint['VpcEndpointId']} is already checked for VPC ID: {vpc_id}, AZ: {az}")
                if vpc_az_is_pub_memo[f'{vpc_id}-{az}']:
                    result(f"vpce: {endpoint['VpcEndpointId']}, az: {az}, vpc: {vpc_id}, service: {endpoint['ServiceName']}")
                continue
            vpc_az_is_pub_memo[f'{vpc_id}-{az}'] = False
            subnets_response = ec2_client.describe_subnets(
                Filters=[
                    {'Name': 'availability-zone', 'Values': [az]},
                    {'Name': 'vpc-id', 'Values': [vpc_id]}
                ]
            )

            all_subnets_count = len(subnets_response['Subnets'])
            public_subnets_count = 0
            for subnet in subnets_response['Subnets']:
                debug(f"VPC ID: {vpc_id}, Subnet ID: {subnet['SubnetId']}, AZ: {az}, Endpoint ID: {endpoint['VpcEndpointId']}, Service Name: {endpoint['ServiceName']}")
                if is_public_subnet(ec2_client, subnet['SubnetId']):
                    public_subnets_count += 1
                debug(f"Public Subnets Count: {public_subnets_count}, All Subnets Count: {all_subnets_count}")
                if public_subnets_count == all_subnets_count:
                    vpc_az_is_pub_memo[f'{vpc_id}-{az}'] = True

            if vpc_az_is_pub_memo[f'{vpc_id}-{az}']:
                result(f"vpce: {endpoint['VpcEndpointId']}, az: {az}, vpc: {vpc_id}, service: {endpoint['ServiceName']}")

if __name__ == '__main__':
    region = 'ap-northeast-1'
    if len(sys.argv) > 1:
        if sys.argv[1] == '--help':
            print(f"Usage: {sys.argv[0]} --region <region>")
            sys.exit(0)
        if sys.argv[1] == '--region':
            region = sys.argv[2]
    main(region)
