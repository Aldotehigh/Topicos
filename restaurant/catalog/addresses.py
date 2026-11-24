import re
from rest_framework import serializers


class AddressSerializer(serializers.Serializer):
    recipient = serializers.CharField(min_length=2, max_length=100)
    phone = serializers.CharField(max_length=25)
    street = serializers.CharField(min_length=2, max_length=100)
    number = serializers.CharField(max_length=20)
    neighborhood = serializers.CharField(min_length=2, max_length=80)
    city = serializers.CharField(min_length=2, max_length=80)
    state = serializers.CharField(min_length=2, max_length=80)
    postal_code = serializers.RegexField(r'^(?!00000)\d{5}$')
    references = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')

    def validate_phone(self, value):
        digits = re.sub(r'\D', '', value)
        if len(digits) == 12 and digits.startswith('52'):
            digits = digits[2:]
        if len(digits) != 10 or len(set(digits)) == 1:
            raise serializers.ValidationError('Enter a valid 10-digit contact phone number.')
        return digits
