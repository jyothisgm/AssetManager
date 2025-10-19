from rest_framework import serializers
from .models import Bill, BillItem

class BillItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillItem
        fields = [
            'id',
            'bill',
            'name',
            'quantity',
            'unit',
            'price',
            'created_at',
            'modified_at'
        ]
        read_only_fields = ['id', 'created_at', 'modified_at']


class BillSerializer(serializers.ModelSerializer):
    items = BillItemSerializer(many=True, read_only=True)

    class Meta:
        model = Bill
        fields = [
            'id',
            'store_name',
            'bill_date',
            'category',
            'total_amount',
            'uploaded_at',
            'image',
            'processed',
            'created_at',
            'modified_at',
            'items'
        ]
        read_only_fields = ['id', 'processed', 'created_at', 'modified_at']
