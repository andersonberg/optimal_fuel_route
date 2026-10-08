from django.db import models


class TruckStop(models.Model):
    opis_id = models.IntegerField()
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    rack_id = models.IntegerField()
    retail_price = models.DecimalField(max_digits=12, decimal_places=8)
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.name


class Place(models.Model):
    """A US city/town from the Census gazetteer, looked up by normalized name."""

    state = models.CharField(max_length=2)
    key = models.CharField(max_length=100)
    lat = models.FloatField()
    lng = models.FloatField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['state', 'key'], name='unique_place_state_key'),
        ]

    def __str__(self):
        return f'{self.key}, {self.state}'
