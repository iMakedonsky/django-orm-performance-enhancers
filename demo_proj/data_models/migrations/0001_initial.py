# Generated by Django 4.1.7 on 2023-05-30 21:15

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Address',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
        ),
        migrations.CreateModel(
            name='Ride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
        ),
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('address', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='users', to='data_models.address')),
            ],
        ),
        migrations.CreateModel(
            name='Vehicle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('make', models.CharField(choices=[('bmw', 'Bmw'), ('ford', 'Ford'), ('toyota', 'Toyota')], default='bmw', max_length=100)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='vehicles', to='data_models.user')),
                ('parking_address', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='parked_vehicles', to='data_models.address')),
            ],
        ),
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type', models.CharField(choices=[('payment', 'Payment'), ('refund', 'Refund'), ('charge', 'Charge')], default='payment', max_length=10)),
                ('user_id', models.PositiveSmallIntegerField(help_text='Intentionally unlinked user_id to test prefetch_unrelated')),
                ('parent', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='children', to='data_models.transaction')),
                ('ride', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='transactions', to='data_models.ride')),
            ],
        ),
        migrations.AddField(
            model_name='ride',
            name='driver',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='driver_rides', to='data_models.user'),
        ),
        migrations.AddField(
            model_name='ride',
            name='end_point',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rides_ending_here', to='data_models.address'),
        ),
        migrations.AddField(
            model_name='ride',
            name='passenger',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='passenger_rides', to='data_models.user'),
        ),
        migrations.AddField(
            model_name='ride',
            name='start_point',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rides_starting_here', to='data_models.address'),
        ),
        migrations.AddField(
            model_name='ride',
            name='vehicle',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rides', to='data_models.vehicle'),
        ),
    ]
