from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import builder


@api_view(["GET"])
def rings(request):
    """All fraud-ring clusters (2+ buyers sharing an address or phone), worst first."""
    return Response({"results": builder.find_rings()})


@api_view(["GET"])
def buyer_graph(request, payer_id: str):
    """React Flow nodes and edges for the cluster around one buyer."""
    data = builder.buyer_graph(payer_id)
    if data is None:
        return Response({"detail": "buyer not found"}, status=404)
    return Response(data)
