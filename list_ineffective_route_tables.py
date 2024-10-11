import boto3
import sys
import datetime

class EndpointType:
    S3 = 's3'
    DYNAMODB = 'ddb'

DEBUG = False
def debug(msg):
    if DEBUG:
        print(f"[debug] {msg}", flush=True, file=sys.stderr)

# Check if the route_table has a gateway endpoints (S3 and DynamoDB)
# TODO: Check ECR and Kinesis
def get_gateways_in_route(client, route_table):
    endpoint_types = []
    endpoints = []
    for route in route_table['Routes']:
        if not route.get('GatewayId'):
            continue
        if not route['GatewayId'].startswith('vpce-'):
            continue
        debug(f"INFO: Gateway route exists in route table {route_table['RouteTableId']}")
        endpoints.append(route['GatewayId'])
    for endpoint in endpoints:
        # Check if the gateway endpoint type (S3 or DynamoDB)
        response = client.describe_vpc_endpoints(
            VpcEndpointIds=[endpoint]
        )
        for vpc_endpoint in response['VpcEndpoints']:
            service_name = vpc_endpoint['ServiceName']
            if service_name.startswith('com.amazonaws'):
                if service_name.endswith('s3'):
                    debug(f"INFO: Gateway endpoint to S3 exists in route table {route_table['RouteTableId']}")
                    endpoint_types.append(EndpointType.S3)
                elif service_name.endswith('dynamodb'):
                    debug(f"INFO: Gateway endpoint to DynamoDB exists in route table {route_table['RouteTableId']}")
                    endpoint_types.append(EndpointType.DYNAMODB)
    if len(endpoint_types) == 0:
        endpoint_types.append('empty')
    return ','.join(endpoint_types)

def get_ineffective_route_tables(client, nat_gateway_id, vpc_id):
    response = client.describe_route_tables(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
    rtbs = {}
    for route_table in response['RouteTables']:
        if len(route_table['Associations']) == 0:
            continue
        for route in route_table['Routes']:
            if route.get('NatGatewayId') != nat_gateway_id:
                continue
            # Check if the route table is used by at least one subnet
            count = 0
            for association in route_table['Associations']:
                if association.get('SubnetId'):
                    count += 1
            if count == 0:
                continue
            endpoint_types = get_gateways_in_route(client, route_table)
            rtbs[route_table['RouteTableId']] = endpoint_types
    return rtbs

def get_monthly_bytes(client, natgw_id):
    metrics = ['BytesOutToSource', 'BytesOutToDestination']
    total_bytes_processed = 0
    for metric in metrics:
        response = client.get_metric_statistics(
             Namespace='AWS/NATGateway',
             MetricName=metric,
             Dimensions=[
                 {'Name': 'NatGatewayId', 'Value': natgw_id}
             ],
             Period=3600*24*30,
             StartTime=(datetime.datetime.now() - datetime.timedelta(days=30)).isoformat(),
             EndTime=datetime.datetime.now().isoformat(),
             Statistics=['Sum']
        )
        for data_point in response['Datapoints']:
            total_bytes_processed += data_point['Sum']
    return total_bytes_processed

def main(region):
    # List all NAT Gateways and check if they are in available state
    ec2 = boto3.client('ec2', region_name=region)
    cw = boto3.client('cloudwatch', region_name=region)
    response = ec2.describe_nat_gateways()
    for nat_gateway in response['NatGateways']:
        natgw_id = nat_gateway['NatGatewayId']
        if nat_gateway['State'] != 'available':
            debug(f"WARNING: NAT Gateway {natgw_id} is in state {nat_gateway['State']}")
            continue
        total_bytes = get_monthly_bytes(cw, natgw_id)
        cost_estimate = round(total_bytes * 0.064 / 1024 / 1024 / 1024, 2)
        # Check if the subnets in the VPC that NAT Gateway located
        # have a route to the NAT Gateway
        rtbs = get_ineffective_route_tables(ec2, nat_gateway['NatGatewayId'] ,nat_gateway['VpcId'])
        for rtb, endpoint_types in rtbs.items():
            print(f"{natgw_id}\t{total_bytes}\t{cost_estimate}\t{rtb}\t{endpoint_types}")
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
