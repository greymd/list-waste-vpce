import boto3
import sys
import datetime

class SubnetType:
    PUBLIC = 0
    HALF_PUBLIC = 1
    PRIVATE = 2

DEBUG = False
def debug(msg):
    if DEBUG:
        print(f"[debug] {msg}", flush=True, file=sys.stderr)

def result(account_id, cw_client, vpc_id, az, endpoint_id, service_name, subnet_type):
    if subnet_type == SubnetType.PRIVATE:
        return
    subnet_type_str = 'SAFE_TO_DELETE'
    if subnet_type == SubnetType.HALF_PUBLIC:
        subnet_type_str = 'CHECK_MANUALLY'
    # Check total ByteProcessed metric in 30 days from CloudWatch
    response = cw_client.get_metric_statistics(
        Namespace='AWS/PrivateLinkEndpoints',
        MetricName='BytesProcessed',
        Dimensions=[
            {'Name': 'VPC Id', 'Value': vpc_id},
            {'Name': 'VPC Endpoint Id', 'Value': endpoint_id},
            {'Name': 'Endpoint Type', 'Value': 'Interface'},
            {'Name': 'Service Name', 'Value': service_name}
        ],
        Period=3600*24*30,
        StartTime=(datetime.datetime.now() - datetime.timedelta(days=30)).isoformat(),
        EndTime=datetime.datetime.now().isoformat(),
        Statistics=['Sum']
    )
    total_bytes_processed = 0
    for data_point in response['Datapoints']:
        total_bytes_processed += data_point['Sum']
    print(f"\033[91m{account_id}\t{vpc_id}\t{az}\t{subnet_type_str}\t{endpoint_id}\t{service_name}\t{total_bytes_processed}\033[0m", flush=True, file=sys.stdout)

# Check if the subnet has any ENIs without public IP address
def has_private_eni(ec2_client, subnet_id):
    response = ec2_client.describe_network_interfaces(
        Filters=[
            {'Name': 'subnet-id', 'Values': [subnet_id]}
        ]
    )
    for eni in response['NetworkInterfaces']:
        if not eni.get('Association'):
            debug(f"Private ENI -- Subnet ID: {subnet_id}, ENIs: {eni['NetworkInterfaceId']}")
            return True
            # continue
        if not eni['Association'].get('PublicIp'):
            debug(f"Private ENI -- Subnet ID: {subnet_id}, ENIs: {eni['NetworkInterfaceId']}")
            return True
    return False

def is_public_subnet(ec2_client, subnet_id):
    any_private_eni = has_private_eni(ec2_client, subnet_id)
    response = ec2_client.describe_route_tables(
        Filters=[
            {'Name': 'association.subnet-id', 'Values': [subnet_id]}
        ]
    )
    for route_table in response['RouteTables']:
        for route in route_table['Routes']:
            if route.get('DestinationCidrBlock') == '0.0.0.0/0':
                if 'GatewayId' in route and route['GatewayId'].startswith('igw-'):
                    if any_private_eni:
                        debug(f"Subnet ID: {subnet_id} = HALF_PUBLIC")
                        return SubnetType.HALF_PUBLIC
                    else:
                        debug(f"Subnet ID: {subnet_id} = PUBLIC")
                        return SubnetType.PUBLIC
                if 'NatGatewayId' in route:
                    debug(f"Subnet ID: {subnet_id} = PUBLIC")
                    return SubnetType.PUBLIC
    debug(f"Subnet ID: {subnet_id} = PRIVATE")
    return SubnetType.PRIVATE

def main(region):
    account_id = boto3.client('sts').get_caller_identity().get('Account')
    cw_client = boto3.client('cloudwatch', region_name=region)
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
                result(account_id,
                       cw_client,
                       vpc_id,
                       az,
                       endpoint['VpcEndpointId'],
                       endpoint['ServiceName'],
                       vpc_az_is_pub_memo[f'{vpc_id}-{az}'])
                continue
            vpc_az_is_pub_memo[f'{vpc_id}-{az}'] = SubnetType.PRIVATE
            subnets_response = ec2_client.describe_subnets(
                Filters=[
                    {'Name': 'availability-zone', 'Values': [az]},
                    {'Name': 'vpc-id', 'Values': [vpc_id]}
                ]
            )

            subnet_types = []
            for subnet in subnets_response['Subnets']:
                subnet_type = is_public_subnet(ec2_client, subnet['SubnetId'])
                subnet_types.append(subnet_type)

            # Check if any subnets is private
            if SubnetType.PRIVATE in subnet_types:
                vpc_az_is_pub_memo[f'{vpc_id}-{az}'] = SubnetType.PRIVATE
            else:
                if SubnetType.HALF_PUBLIC in subnet_types:
                    vpc_az_is_pub_memo[f'{vpc_id}-{az}'] = SubnetType.HALF_PUBLIC
                else:
                    vpc_az_is_pub_memo[f'{vpc_id}-{az}'] = SubnetType.PUBLIC

            result(account_id,
                   cw_client,
                   vpc_id,
                   az,
                   endpoint['VpcEndpointId'],
                   endpoint['ServiceName'],
                   vpc_az_is_pub_memo[f'{vpc_id}-{az}'])

if __name__ == '__main__':
    region = 'ap-northeast-1'
    if len(sys.argv) > 1:
        if sys.argv[1] == '--help':
            print(f"Usage: {sys.argv[0]} --region <region>")
            sys.exit(0)
        if sys.argv[1] == '--region':
            region = sys.argv[2]
    main(region)
