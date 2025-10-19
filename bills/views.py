from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Bill, BillItem
from .serializers import BillSerializer, BillItemSerializer
from .utils import process_bill_image


class BillViewSet(viewsets.ModelViewSet):
    queryset = Bill.objects.all().order_by('-created_at')
    serializer_class = BillSerializer

    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        bill = self.get_object()
        if not bill.processed and bill.image:
            data = process_bill_image(bill.image.path)
            bill.store_name = data.get('store_name', '')
            bill.bill_date = data.get('bill_date')
            bill.category = data.get('category', '')
            bill.total_amount = data.get('total_amount')
            bill.save()

            for item_data in data.get('items', []):
                BillItem.objects.create(bill=bill, **item_data)

            bill.processed = True
            bill.save()
        return Response(BillSerializer(bill).data)


class BillItemViewSet(viewsets.ModelViewSet):
    queryset = BillItem.objects.all().order_by('-created_at')
    serializer_class = BillItemSerializer
