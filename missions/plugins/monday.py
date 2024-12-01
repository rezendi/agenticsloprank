from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport
from ..util import MONDAY_API
from missions import plugins


@plugins.hookimpl
def run_api(task):
    if task.url and task.url.startswith(MONDAY_API):
        get_monday_data(task)
        return task
    return None


def get_monday_token(task):
    if task.get_project():
        secrets = task.get_project().secret_set.filter(vendor="monday")
    if not secrets:
        secrets = task.get_customer().secret_set.filter(vendor="monday")
    if secrets.count() == 0:
        raise Exception("No Monday token found")
    access_token = secrets.last().value
    return access_token


def get_monday_data(task):
    token = get_monday_token(task)
    headers = {"Authorization": "Bearer %s" % token, "Content-Type": "application/json"}
    transport = AIOHTTPTransport(url=MONDAY_API, headers=headers)
    client = Client(transport=transport, fetch_schema_from_transport=True)

    query = gql(
        """
query {
  boards(limit:5) {
    name
    
    columns {
      title
      id
      type
    }
    
    groups {
    	title
      id
    }

    items_page {
      cursor
      items {
        id 
        name 
      }
    }
  }
}
"""
    )
    result = client.execute(query)
    task.response = "%s" % result
